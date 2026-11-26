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
async function run() {
  fs.mkdirSync(dir,{recursive:true});
  status.install='installing'; save();
  await unpack();
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
  let last='';
  async function reconcile() {
    const raw=fs.readFileSync(path.join(dir,'desired.json'),'utf8');
    if(last===raw) return;
    const desired=JSON.parse(raw); last=raw;
    for(const [name,port] of Object.entries(ports)) {
      const current=workers.get(name);
      if(!desired[name]) {
        if(current){workers.delete(name); await current.terminate();}
        status[name]='stopped'; save(); continue;
      }
      if(current) continue;
      status[name]='starting'; save();
      const worker=new Worker(path.join(bundle,'gateway-worker.cjs'),{workerData:{name,root,port},env:{...env,...config[name],PORT:String(port)}});
      workers.set(name,worker);
      worker.on('message',message=>{if(workers.get(name)===worker){status[name]=message;save();}});
      worker.on('error',err=>{if(workers.get(name)===worker){status[name]='error: '+err.message;save();}});
      worker.on('exit',code=>{if(workers.get(name)===worker){workers.delete(name);if(!status[name].startsWith('error:')) status[name]='error: worker exited '+code;save();}});
    }
  }
  for(;;){await reconcile();await new Promise(r=>setTimeout(r,500));}
}
run().catch(error=>{status.install='error: '+error.message;save();});
