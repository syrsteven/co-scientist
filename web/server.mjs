import { promises as fs, existsSync } from "node:fs";
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";

const execute = promisify(execFile);
const root = fileURLToPath(new URL("../", import.meta.url));
const publicRoot = join(root, "web/public");
export const exportFiles = ["manifest", "hypotheses", "hypothesis_projections", "reviews",
  "novelty_assessments", "proximity", "matches", "ratings", "tasks", "costs",
  "convergence_checkpoints", "stop_decisions", "literature", "external_calls",
  "tournament_epochs", "budget_reservations", "full_workflow_check"];
const staticFiles = { "/": ["index.html", "text/html"], "/index.html": ["index.html", "text/html"],
  "/app.js": ["app.js", "text/javascript"], "/model.js": ["model.js", "text/javascript"],
  "/retry.js": ["retry.js", "text/javascript"],
  "/scientist.js": ["scientist.js", "text/javascript"],
  "/styles.css": ["styles.css", "text/css"],
  "/settings.js": ["settings.js", "text/javascript"],
  "/settings-model.js": ["settings-model.js", "text/javascript"],
  "/settings.css": ["settings.css", "text/css"] };

export function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k,v]) =>
    [k, /^(api[_-]key|authorization|access[_-]token|secret|password)$/i.test(k) ? "[redacted]" : redact(v)]));
  return value;
}

export function createCockpitServer({ repoRoot = root, dataDir = process.env.CO_SCIENTIST_DATA_DIR,
  python = process.env.CO_SCIENTIST_PYTHON || join(root, ".venv/bin/python"), bridge, settingsBridge, controlBridge, retryBridge } = {}) {
  const retry = retryBridge || ((database, runId, command, payload) => new Promise((done,reject)=>{
    const args=["-m","co_scientist.application.cockpit_retry","--database",database,"--run-id",runId,
      ...(command==="raw"?[`--call-id=${payload.external_call_id}`]:[]),command];
    const child=execFile(python,args,{cwd:root,timeout:30000,maxBuffer:2*1024*1024},(error,stdout)=>{
      if(error)return reject(error);try{done(JSON.parse(stdout));}catch(error){reject(error);}
    });
    child.stdin.on("error",()=>{});child.stdin.end(command!=="raw"?JSON.stringify(payload):"");
  }));
  const control = controlBridge || ((database, runId, payload) => new Promise((done,reject)=>{
    const child=execFile(python,["-m","co_scientist.application.cockpit_control","--database",database,"--run-id",runId],
      {cwd:root,timeout:30000,maxBuffer:1024*1024},(error,stdout)=>{
        if(error)return reject(error);try{done(JSON.parse(stdout));}catch(error){reject(error);}
      });
    child.stdin.on("error",()=>{});child.stdin.end(JSON.stringify(payload));
  }));
  const settings = settingsBridge || ((command, payload) => new Promise((done, reject) => {
    const child = execFile(python, ["-m", "co_scientist.application.cockpit_settings",
      "--root", repoRoot, command], {cwd:root, timeout:15000, maxBuffer:4*1024*1024},
    (error, stdout) => { if(error)return reject(error); try {done(JSON.parse(stdout));}catch(error){reject(error);} });
    child.stdin.on("error",()=>{});
    child.stdin.end(payload === undefined ? "" : JSON.stringify(payload));
  }));
  const read = bridge || (async (database, command, runId) => {
    const { stdout } = await execute(python, ["-m", "co_scientist.application.cockpit",
      "--database", database, command, ...(runId ? [runId] : [])],
    { cwd: root, timeout: 30000, maxBuffer: 64 * 1024 * 1024 });
    return JSON.parse(stdout);
  });
  let catalog = new Map();
  const pending = new Map();
  async function inventory() {
    const entries = await fs.readdir(repoRoot, { withFileTypes: true });
    const next = new Map(), warnings = [];
    const directories = dataDir ? [resolve(repoRoot, dataDir)] : entries
      .filter(e => e.isDirectory() && e.name.startsWith(".co-scientist"))
      .map(e => join(repoRoot, e.name));
    for (const directory of directories) {
      const database = join(directory, "co-scientist.db");
      if (!existsSync(database)) continue;
      try {
        for (const run of await read(database, "list")) {
          const id = `db:${basename(directory)}:${run.runId}`;
          next.set(id, { ...run, id, kind: "database", location: basename(directory), database });
        }
      } catch { warnings.push(`${basename(directory)} 无法读取；请检查 Python 环境和数据库版本。`); }
    }
    for (const entry of entries.filter(e => e.isDirectory() && e.name.endsWith("-export"))) {
      try {
        const manifestPath = join(repoRoot, entry.name, "manifest.json");
        if ((await fs.lstat(manifestPath)).isSymbolicLink()) continue;
        const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
        const id = `export:${entry.name}`;
        if (typeof manifest.run_id !== "string") continue;
        next.set(id, { id, runId: manifest.run_id, state: manifest.final_state,
          kind: "local-export", location: entry.name, directory: entry.name });
      } catch { /* Incomplete exports are not selectable. */ }
    }
    catalog = next;
    return { runs: [...next.values()].map(({ database, directory, ...run }) => run)
      .sort((a,b) => a.kind.localeCompare(b.kind) || String(b.updatedAt||"").localeCompare(String(a.updatedAt||"")) || b.runId.localeCompare(a.runId)), warnings };
  }
  async function getSnapshot(id) {
    if (!catalog.has(id)) await inventory();
    const run = catalog.get(id);
    if (!run) return null;
    if (pending.has(id)) return pending.get(id);
    const promise = (async () => {
      let data;
      if (run.kind === "database") data = await read(run.database, "snapshot", run.runId);
      else {
        data = {};
        for (const name of [...exportFiles, "events"]) {
          const path = join(repoRoot, run.directory, name === "events" ? "events.jsonl" : `${name}.json`);
          try {
            if ((await fs.lstat(path)).isSymbolicLink()) continue;
            const content = await fs.readFile(path, "utf8");
            data[name] = name === "events" ? content.split(/\r?\n/).filter(Boolean).map(JSON.parse) : JSON.parse(content);
          } catch (error) { if (error.code !== "ENOENT") throw error; }
        }
      }
      return { ...redact(data), _source: { kind: run.kind, location: run.location,
        loadedAt: new Date().toISOString(), controlAvailable: run.kind === "database",
        outputRetryAvailable: run.kind === "database", rawAvailable: run.kind === "database",
        scientistFeedbackAvailable: run.kind === "database",
        pollIntervalMs: run.kind === "database" ? 5000 : null } };
    })();
    pending.set(id, promise);
    try { return await promise; } finally { pending.delete(id); }
  }
  return createServer(async (req,res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'");
    const json = (status, value) => { res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" }); res.end(JSON.stringify(value)); };
    try {
      const host = req.headers.host || "";
      if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) return json(403, {error:"Local access only"});
      if (req.headers.origin && req.headers.origin !== `http://${host}`) return json(403, {error:"Cross-origin access denied"});
      const url = new URL(req.url, `http://${host}`);
      const controlMatch=url.pathname.match(/^\/api\/runs\/([^/]+)\/control$/);
      const retryMatch=url.pathname.match(/^\/api\/runs\/([^/]+)\/retry-output$/);
      const scientistMatch=url.pathname.match(/^\/api\/runs\/([^/]+)\/scientist-feedback$/);
      if (req.method === "POST" && (controlMatch || retryMatch || scientistMatch || /^\/api\/settings\/(validate|save)$/.test(url.pathname))) {
        if(req.headers.origin !== `http://${host}`)return json(403,{error:"Same-origin required"});
        if(!/^application\/json(?:;|$)/i.test(req.headers["content-type"]||""))return json(415,{error:"JSON required"});
        const chunks=[];let size=0;
        for await (const chunk of req) {
          size+=chunk.length;
          if(size>256*1024)return json(413,{error:"配置超过 256 KB"});
          chunks.push(chunk);
        }
        let payload;
        try{payload=JSON.parse(Buffer.concat(chunks).toString("utf8"));}catch{return json(400,{error:"无效 JSON"});}
        if(controlMatch||retryMatch||scientistMatch){
          const id=decodeURIComponent((controlMatch||retryMatch||scientistMatch)[1]);
          if(!catalog.has(id))await inventory();
          const run=catalog.get(id);
          if(!run)return json(404,{error:"Unknown run"});
          if(run.kind!=="database")return json(409,{error:"导出快照不可控制。"});
          const result=scientistMatch?await retry(run.database,run.runId,"scientist-feedback",payload):retryMatch?await retry(run.database,run.runId,"retry",payload):await control(run.database,run.runId,payload);
          return json(result.status|| (result.ok?200:422),result);
        }
        const result=await settings(url.pathname.endsWith("/save")?"save":"validate",payload);
        return json(result.ok?200:422,result);
      }
      if (req.method !== "GET") return json(405, {error:"仅支持读取、配置保存和已确认的运行控制。"});
      if (url.pathname === "/api/settings") return json(200,await settings("catalog"));
      if (url.pathname === "/api/runs") return json(200, await inventory());
      const rawMatch=url.pathname.match(/^\/api\/runs\/([^/]+)\/calls\/([^/]+)\/raw$/);
      if(rawMatch){
        const id=decodeURIComponent(rawMatch[1]);
        if(!catalog.has(id))await inventory();
        const run=catalog.get(id);
        if(!run)return json(404,{error:"Unknown run"});
        if(run.kind!=="database")return json(409,{error:"导出文件请在本地查看，不通过此接口读取。"});
        const result=await retry(run.database,run.runId,"raw",{external_call_id:decodeURIComponent(rawMatch[2])});
        return json(result.status||(result.ok?200:422),result);
      }
      const match = url.pathname.match(/^\/api\/runs\/([^/]+)\/snapshot$/);
      if (match) {
        const data = await getSnapshot(decodeURIComponent(match[1]));
        return json(data ? 200 : 404, data || {error:"Unknown run"});
      }
      const asset = staticFiles[url.pathname];
      if (!asset) return json(404, {error:"Not found"});
      const content = await fs.readFile(join(publicRoot, asset[0]));
      res.writeHead(200, {"Content-Type": `${asset[1]}; charset=utf-8`}); res.end(content);
    } catch { json(503, {error:req.method==="POST" ? "请求未确认完成，请刷新核对状态；不要盲目重复提交。" : "无法读取数据。请检查 Python 环境、数据库版本或导出文件；读取不会修改运行。"}); }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.CO_SCIENTIST_WEB_PORT || 4173);
  createCockpitServer().listen(port, "127.0.0.1", () => {
    console.log(`Co-Scientist cockpit: http://127.0.0.1:${port} (local cockpit; explicit lifecycle controls)`);
  });
}
