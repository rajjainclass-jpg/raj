import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('./public/checkout.js',import.meta.url),'utf8');
async function page(hash,result={paymentDetails:{paymentMessage:'fixture'}}){
 const nodes=new Map(); const history=[]; let checkoutCalls=0;let options;
 const node=()=>({hidden:true,disabled:false,textContent:'',href:'',children:[],handlers:{},replaceChildren(){this.children=[];},append(v){this.children.push(v);},addEventListener(k,fn){this.handlers[k]=fn;}});
 for(const id of ['status','reference','pay','return','products'])nodes.set(id,node());
 const window={location:{hash,search:'',pathname:'/'},history:{replaceState(...a){history.push(a);}},Cashfree:({mode})=>({async checkout(input){checkoutCalls++;options={mode,...input};return result;}})};
 const context={window,document:{getElementById:id=>nodes.get(id),createElement:()=>node()},URLSearchParams,Intl,fetch:async()=>({ok:true,json:async()=>({products:[]})})};
 vm.runInNewContext(source,context);await Promise.resolve();await Promise.resolve();
 return {nodes,history,get calls(){return checkoutCalls;},get options(){return options;}};
}
const token='fixture-scoped-session';const order='rkp_'+'a'.repeat(32);
let p=await page('#session='+token+'&order='+order+'&mode=production');
assert.equal(p.history[0][2],'/');assert.equal(p.nodes.get('pay').hidden,false);await p.nodes.get('pay').handlers.click();
assert.equal(p.calls,1);assert.equal(p.options.paymentSessionId,token);assert.equal(p.options.redirectTarget,'_modal');assert.match(p.nodes.get('status').textContent,/verify your payment status/);
p=await page('#session='+token+'&order='+order+'&mode=production',{error:{message:'domain not approved'}});await p.nodes.get('pay').handlers.click();assert.match(p.nodes.get('status').textContent,/domain not approved/);
p=await page('#session='+token+'&order=%3Cscript%3E&mode=production');assert.equal(p.nodes.get('pay').hidden,true);assert.equal(p.calls,0);
p=await page('');assert.equal(p.nodes.get('pay').hidden,true);assert.equal(p.calls,0);
console.log('PASS: browser checkout fragment privacy, provider handoff, pending verification, provider error and invalid-link checks.');
