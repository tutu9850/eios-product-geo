const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const ts=require('/Users/tutu/eios-product-geo/node_modules/typescript');
let source=fs.readFileSync('/Users/tutu/eios-product-geo/packages/geo/src/geo-advisor/GeoContentGenForm.tsx','utf8');
source=source.replace('  const inputClass =',`  globalThis.controls = {generate,runImprove,runQuality,saveToAssets,setTopic,setGoal,setContentType,setStyle,setImproveText,setResult,setScore,setQuality,invalidateDraft,result,score,quality,savedNote,loading,improving,qualityLoading};\n  const inputClass =`);
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
let slots=[],index=0,requests=[];
const react={useState(initial){const i=index++;if(!(i in slots))slots[i]=initial;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v}]},useRef(initial){const i=index++;if(!(i in slots))slots[i]={current:initial};return slots[i]},useEffect(){}};
const api={geoPost(path,body,signal){let resolve,reject;const p=new Promise((a,b)=>{resolve=a;reject=b});requests.push({path,body,signal,resolve,reject});return p},geoGet:async()=>({items:[]})};
const sandbox={exports:{},AbortController,Set,setTimeout,clearTimeout,console,globalThis:null,require(name){if(name==='react')return react;if(name==='react/jsx-runtime')return{jsx:()=>null,jsxs:()=>null};if(name==='./geo-api')return api;if(name==='./shared')return{useGeoNavParams:()=>({})};if(name==='./geo-monitor-subject')return{useMonitorSubject:()=>({scopeQuery:'',subject:null})};return{cn:()=>'',Button:()=>null}}};sandbox.globalThis=sandbox;vm.runInNewContext(compiled,sandbox);
function render(){index=0;sandbox.exports.GeoContentGenForm();return sandbox.controls}
function reset(){slots=[];requests=[];render()}
function configure(){const c=render();c.setTopic('主题');c.setGoal('目标');c.setContentType('企业介绍');c.setStyle('专业');return render()}
async function tick(){await new Promise(setImmediate)}
const watchdog=setTimeout(()=>{console.error("timing harness did not complete");process.exit(1)},5000);
(async()=>{
 console.log("next scenario",requests.map(r=>r.path)); reset();let c=configure();c.setResult({ok:true,title:'旧',content:'旧正文',fact_check:{score:1},unverified_facts:[{claim:'旧'}],sections:{旧:'旧'}});c.setScore({total:1});c.setQuality({total:99});c.setImproveText('缩短');c=render();const rewrite=c.runImprove();assert.equal(render().quality,null);assert.equal(render().score,null);requests[0].resolve({content:'新正文',title:'新'});await rewrite;c=render();assert.equal(c.result.fact_check,null);assert.equal(c.result.unverified_facts.length,0);assert.equal(c.result.sections,null);
 console.log("next scenario",requests.map(r=>r.path)); reset();c=configure();c.setResult({ok:true,content:'旧正文'});c=render();const quality=c.runQuality();const old= requests[0];c=render();const generation=c.generate();assert.equal(old.signal.aborted,true);assert.equal(render().result,null);requests[1].resolve({ok:true,title:'新',content:'新正文'});await tick();assert.equal(requests[2].path,'/content/score');requests[2].resolve({total:.5});await generation;old.resolve({total:99});await quality;c=render();assert.equal(c.quality,null);assert.equal(c.result.content,'新正文');assert.equal(c.score.total,.5);
 console.log("next scenario",requests.map(r=>r.path)); reset();c=configure();const first=c.generate();requests[0].resolve({ok:true,content:'第一稿'});await tick();const oldScore=requests[1];c=render();const second=c.generate();requests[2].resolve({ok:true,content:'第二稿'});await tick();requests[3].resolve({total:.8});await second;oldScore.resolve({total:1});await first;c=render();assert.equal(c.result.content,'第二稿');assert.equal(c.score.total,.8);
 console.log("next scenario",requests.map(r=>r.path)); reset();c=configure();c.setResult({ok:true,title:'稿',content:'正文'});c=render();const save=c.saveToAssets();c=render();c.setImproveText('改稿');c=render();console.log("save check",requests.length);await c.runImprove();await c.generate();assert.equal(requests.length,1);requests[0].resolve({item:{title:'稿'}});await save;assert.match(render().savedNote,/已存入/);
 clearTimeout(watchdog);
 console.log('4 actual component closure timing scenarios passed (hook harness; no DOM/Host assertion)');
})().catch(e=>{console.error(e);process.exitCode=1});
