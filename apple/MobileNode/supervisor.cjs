'use strict';
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const {Worker} = require('node:worker_threads');
const dir = process.argv[2];
const bundle = process.argv[3];
const revision = 'omni-3.8.54_free-0.16.39-1';
const root = path.join(dir, revision);
const status = {};
const workers = new Map();
const ports = {omni:20128, free:3001};
function save() {
  const file = path.join(dir,'state.json');
  fs.writeFileSync(file+'.tmp',JSON.stringify(status));
  fs.renameSync(file+'.tmp',file);
}
async function unpack() {
  if(fs.existsSync(path.join(root,'.ready'))) return;
  const temp=root+'.install';
  fs.rmSync(temp,{force:true,recursive:true});
  fs.mkdirSync(temp,{recursive:true});
  const input=fs.createReadStream(path.join(bundle,'gateways.dat')).pipe(zlib.createGunzip());
  const chunks=input[Symbol.asyncIterator]();
  let buffer=Buffer.alloc(0);
  async function fill() {
    if(buffer.length) return;
    const part=await chunks.next();
    if(part.done) throw Error('Incomplete gateway archive');
    buffer=part.value;
  }
  async function read(n) {
    const out=Buffer.alloc(n);
    let pos=0;
    while(pos<n) {
      await fill();
      const len=Math.min(buffer.length,n-pos);
      buffer.copy(out,pos,0,len); buffer=buffer.subarray(len); pos+=len;
    }
    return out;
  }
  try {
    for(;;) {
      const hdr=await read(8);
      const length=hdr.readUInt32BE(), size=hdr.readUInt32BE(4);
      if(length===0 && size===0) break;
      if(length<1 || length>4096) throw Error('Invalid archive path');
      const rel=(await read(length)).toString();
      if(rel.split('/').some(p=>!p || p==='.' || p==='..')) throw Error('Invalid archive entry');
      const dest=path.join(temp,rel);
      fs.mkdirSync(path.dirname(dest),{recursive:true});
      const fd=fs.openSync(dest,'wx',0o600);
      try {
        let left=size;
        while(left) {
          await fill();
          const len=fs.writeSync(fd,buffer,0,Math.min(left,buffer.length));
          if(!len) throw Error('Incomplete file write');
          left-=len; buffer=buffer.subarray(len);
        }
      } finally { fs.closeSync(fd); }
    }
    if(buffer.length || !(await chunks.next()).done) throw Error('Unexpected archive data');
    fs.writeFileSync(path.join(temp,'.ready'),'1');
    fs.renameSync(temp,root);
  } finally { input.destroy(); }
}
function secret(name) {
  const file=path.join(dir,name);
  if(!fs.existsSync(file)) fs.writeFileSync(file,crypto.randomBytes(32).toString('hex'),{mode:0o600,flag:'wx'});
  return fs.readFileSync(file,'utf8');
}
// A request file lets the app retry immediately instead of waiting for the backoff.
function takeRequest(name) {
  const file=path.join(dir,'restart-'+name);
  if(!fs.existsSync(file)) return false;
  fs.rmSync(file,{force:true});
  return true;
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function install() {
  for(;;) {
    status.install='installing'; save();
    try { await unpack(); return; }
    catch(error) {
      status.install='error: '+error.message; save();
      while(!takeRequest('install')) await sleep(1000);
    }
  }
}
async function run() {
  fs.mkdirSync(dir,{recursive:true});
  await install();
  process.chdir(path.join(root,'omni'));
  status.install='ready'; save();
  const env={...process.env,NODE_ENV:'production',NEXT_TELEMETRY_DISABLED:'1',
    ARENA_ELO_SYNC_ENABLED:'false',MODELS_DEV_SYNC_ENABLED:'false',PRICING_SYNC_ENABLED:'false',
    FREE_PROXY_AUTO_SYNC_ENABLED:'false',CATALOG_SYNC_DISABLED:'1',HOST:'127.0.0.1',HOSTNAME:'127.0.0.1'};
  const data=path.join(dir,'accounts');
  fs.mkdirSync(data,{recursive:true});
  const config={
    omni:{DATA_DIR:path.join(data,'omni'),JWT_SECRET:secret('jwt'),INITIAL_PASSWORD:secret('omni-password'),STORAGE_ENCRYPTION_KEY:secret('omni-key')},
    free:{FREEAPI_DB_PATH:path.join(data,'free','gateway.db'),ENCRYPTION_KEY:secret('free-key'),CLIENT_DIST:path.join(root,'free/client/dist'),ALLOWED_HOSTS:'127.0.0.1'}
  };
  const failures={}, retryAt={};
  function readDesired() {
    try { return JSON.parse(fs.readFileSync(path.join(dir,'desired.json'),'utf8')); }
    catch { return {}; }
  }
  function launch(name,port) {
    status[name]='starting'; save();
    const worker=new Worker(path.join(bundle,'gateway-worker.cjs'),{workerData:{name,root,port},env:{...env,...config[name],PORT:String(port)}});
    workers.set(name,worker);
    const failed=reason=>{
      if(workers.get(name)!==worker) return;
      workers.delete(name);
      failures[name]=(failures[name]||0)+1;
      // Retry crashed gateways automatically: 2s, 4s, 8s ... up to one minute.
      retryAt[name]=Date.now()+Math.min(60000,1000*2**failures[name]);
      status[name]='error: '+reason; save();
      worker.terminate().catch(()=>{});
    };
    worker.on('message',message=>{
      if(workers.get(name)!==worker) return;
      if(typeof message==='string' && message.startsWith('error:')) return failed(message.slice(6).trim());
      if(message==='listening') failures[name]=0;
      status[name]=message; save();
    });
    worker.on('error',err=>failed(err.message));
    worker.on('exit',code=>failed('worker exited '+code));
  }
  async function reconcile() {
    const desired=readDesired();
    for(const [name,port] of Object.entries(ports)) {
      const current=workers.get(name);
      const forced=takeRequest(name);
      if(!desired[name]) {
        if(current){workers.delete(name); await current.terminate();}
        failures[name]=0; delete retryAt[name];
        if(status[name]!=='stopped'){status[name]='stopped'; save();}
        continue;
      }
      if(current && !forced) continue;
      if(current){workers.delete(name); await current.terminate();}
      if(!forced && retryAt[name] && Date.now()<retryAt[name]) continue;
      if(forced) failures[name]=0;
      delete retryAt[name];
      launch(name,port);
    }
  }
  for(;;){await reconcile();await sleep(500);}
}
run().catch(error=>{status.install='error: '+error.message;save();});
