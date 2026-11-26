'use strict';
const {workerData:{name,root,port},parentPort}=require('node:worker_threads');
const path=require('node:path');
const http=require('node:http');
const net=require('node:net');
const child=require('node:child_process');
const {syncBuiltinESMExports}=require('node:module');
const {pathToFileURL}=require('node:url');
for(const key of ['spawn','spawnSync','fork','exec','execFile','execSync','execFileSync']){
  child[key]=()=>{throw Error('Subprocesses are unavailable in the iOS gateway');};
}
syncBuiltinESMExports();
// Keep automated simulator probes offline, including background fetches.
if (process.env.ALLINONE_OFFLINE_TEST === '1') {
  const connect=net.Socket.prototype.connect;
  net.Socket.prototype.connect=function(...args) {
    const options=net._normalizeArgs(args)[0];
    if(!options.path && !['127.0.0.1','localhost','::1'].includes(options.host ?? 'localhost')) {
      const socket=this;
      queueMicrotask(()=>socket.destroy(Object.assign(Error('Offline test'),{code:'ENETUNREACH'})));
      return socket;
    }
    return connect.apply(this,args);
  };
}
const listen=net.Server.prototype.listen;
net.Server.prototype.listen=function(...args){
  const opts=typeof args[0]==='object'?args[0]:{port:args[0],host:args[1]};
  if(Number(opts?.port)!==port||opts.host!=='127.0.0.1') throw Error('Unexpected gateway listen address');
  this.once('listening',()=>parentPort.postMessage('listening'));
  return listen.apply(this,args);
};
const emit=http.Server.prototype.emit;
http.Server.prototype.emit=function(event,...args){
  if(event==='request'||event==='upgrade'){
    const [req,res]=args;
    const authority='127.0.0.1:'+port;
    const origin=req.headers.origin;
    if(req.headers.host!==authority || (origin && origin!=='http://'+authority) || /(?:mitm|tproxy|token-extract)/i.test(req.url)){
      if(event==='upgrade') res.destroy();
      else {res.writeHead(403);res.end();}
      return true;
    }
  }
  return emit.call(this,event,...args);
};
const entry=path.join(root,name,name==='omni'?'server.js':'server/dist/index.js');
// OmniRoute eagerly imports its optional image processor during startup. Load
// it when an image operation is requested so text routes work on iOS.
if (name === 'omni') {
  const Module = require('node:module');
  const local = Module.createRequire(entry);
  try { local('sharp'); }
  catch {
    const substitute = pathToFileURL(path.join(__dirname,'mobile-sharp.cjs')).href;
    Module.registerHooks({resolve(specifier,context,next) {
      if (specifier === 'sharp') return {url:substitute,shortCircuit:true};
      return next(specifier,context);
    }});
  }
}
import(pathToFileURL(entry)).catch(error=>{parentPort.postMessage('error: '+error.message);process.exitCode=1;});
