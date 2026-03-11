// ===== LP TAB =====
let chartTop, chartBot;
function nvCalc(P,L,sl,sh,pLow,pHigh){
  if(P<=pLow)return L*(1/sl-1/sh)*P;
  if(P>=pHigh)return L*(sh-sl);
  return L*(Math.sqrt(P)-sl)+L*(1/Math.sqrt(P)-1/sh)*P;
}
function computeLP(){
  const pair=document.getElementById('pair').value.trim();
  const pLow=parseFloat(document.getElementById('pLow').value);
  const pHigh=parseFloat(document.getElementById('pHigh').value);
  const pEntry=parseFloat(document.getElementById('pEntry').value);
  const notional=parseFloat(document.getElementById('notional').value);
  const feeApr=parseFloat(document.getElementById('feeApr').value);
  if([pLow,pHigh,pEntry,notional,feeApr].some(isNaN)||pLow>=pHigh)return;
  const sp=Math.sqrt(pEntry),sl=Math.sqrt(pLow),sh=Math.sqrt(pHigh);
  const L=notional/(2*sp-pEntry/sh-sl);
  const x0=L*(1/sp-1/sh),y0=L*(sp-sl);
  const range=pHigh-pLow,pad=range*.12,lo=pLow-pad,hi=pHigh+pad;
  const n=200,prices=[],nots=[],hodls=[],ilPcts=[];
  for(let i=0;i<n;i++){const P=lo+(hi-lo)*i/(n-1);prices.push(P);const v=nvCalc(P,L,sl,sh,pLow,pHigh);nots.push(v);const h=x0*P+y0;hodls.push(h);ilPcts.push((v-h)/h*100);}
  const vLow=nvCalc(pLow,L,sl,sh,pLow,pHigh),vEntry=nvCalc(pEntry,L,sl,sh,pLow,pHigh),vHigh=nvCalc(pHigh,L,sl,sh,pLow,pHigh);
  const hodlLow=x0*pLow+y0,hodlHigh=x0*pHigh+y0;
  const ethAtLow=L*(1/sl-1/sh);
  const ilHodlLow=vLow-hodlLow,ilHodlHigh=vHigh-hodlHigh;
  const ilPctLow=ilHodlLow/hodlLow*100,ilPctHigh=ilHodlHigh/hodlHigh*100;
  const dailyFees=notional*(feeApr/100)/365;
  const daysLow=Math.abs(ilHodlLow)/dailyFees,daysHigh=Math.abs(ilHodlHigh)/dailyFees;
  const parts=pair.split('/'),base=esc(parts[0]||'?'),quote=esc(parts[1]||'?');
  const fmt=v=>'$'+Math.round(v).toLocaleString();
  const vLine=(x,c,l)=>({type:'line',xMin:x,xMax:x,borderColor:c,borderWidth:1.5,borderDash:[6,4],label:{display:true,content:l,position:'start',color:c,font:{size:10},backgroundColor:'transparent'}});
  const vLines={lineLow:vLine(pLow,'rgba(255,107,107,0.6)',`${pLow}`),lineHigh:vLine(pHigh,'rgba(255,107,107,0.6)',`${pHigh}`),lineEntry:vLine(pEntry,'rgba(150,150,150,0.6)',`Entry ${pEntry}`)};
  const dot=(x,y)=>({type:'point',xValue:x,yValue:y,radius:5,backgroundColor:'#ff6b6b',borderColor:'#ff6b6b'});
  const lbl=(x,y,t,xa,ya)=>({type:'label',xValue:x,yValue:y,content:t,color:'#fff',font:{size:11,weight:'bold'},xAdjust:xa,yAdjust:ya,backgroundColor:'rgba(22,33,62,0.9)',padding:4,borderRadius:4});
  const topAnn={...vLines,ptL:dot(pLow,vLow),ptE:dot(pEntry,vEntry),ptH:dot(pHigh,vHigh),lL:lbl(pLow,vLow,[`${fmt(vLow)}`,`(100% ${base})`],-10,-16),lE:lbl(pEntry,vEntry,[`${fmt(vEntry)}`],10,-12),lH:lbl(pHigh,vHigh,[`${fmt(vHigh)}`,`(100% ${quote})`],10,-16)};
  const botAnn={...vLines,ptIL:dot(pLow,ilPctLow),ptIH:dot(pHigh,ilPctHigh),lIL:lbl(pLow,ilPctLow,[`${ilPctLow.toFixed(1)}%`],-30,-14),lIH:lbl(pHigh,ilPctHigh,[`${ilPctHigh.toFixed(1)}%`],30,-14)};
  const scales=l=>({x:{type:'linear',min:lo,max:hi,ticks:{color:'#8892b0',maxTicksLimit:10,callback:v=>Math.round(v)},grid:{color:'#1e3050'},title:{display:true,text:l,color:'#8892b0'}},y:{ticks:{color:'#8892b0'},grid:{color:'#1e3050'}}});
  const opts=(t,a,xl)=>({responsive:true,maintainAspectRatio:false,animation:{duration:200},interaction:{mode:'index',intersect:false},plugins:{tooltip:{mode:'index',intersect:false,callbacks:{title:items=>`${base} Price: $${Math.round(items[0].parsed.x).toLocaleString()}`,label:item=>`${item.dataset.label}: $${Math.round(item.parsed.y).toLocaleString()}`}},title:{display:true,text:t,color:'#e0e0e0',font:{size:13}},legend:{labels:{color:'#8892b0',boxWidth:12,font:{size:11}}},annotation:{annotations:a}},scales:scales(xl)});
  if(chartTop)chartTop.destroy();if(chartBot)chartBot.destroy();
  chartTop=new Chart(document.getElementById('chartTop'),{type:'line',data:{labels:prices,datasets:[{label:'LP Notional',data:nots.map((v,i)=>({x:prices[i],y:v})),borderColor:'#4dabf7',borderWidth:2,pointRadius:0,fill:false},{label:'HODL 50/50',data:hodls.map((v,i)=>({x:prices[i],y:v})),borderColor:'#51cf66',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false}]},options:opts(`${pair.toUpperCase()} Concentrated LP`,topAnn,`${base} Price (${quote})`)});
  chartBot=new Chart(document.getElementById('chartBot'),{type:'line',data:{labels:prices,datasets:[{label:'IL vs HODL (%)',data:ilPcts.map((v,i)=>({x:prices[i],y:v})),borderColor:'#ff6b6b',borderWidth:1.5,pointRadius:0,fill:{target:'origin',above:'rgba(255,107,107,0.05)',below:'rgba(255,107,107,0.2)'}}]},options:{...opts('Impermanent Loss vs 50/50 HODL',botAnn,`${base} Price (${quote})`),plugins:{...opts('','','').plugins,tooltip:{mode:'index',intersect:false,callbacks:{title:items=>`${base} Price: $${Math.round(items[0].parsed.x).toLocaleString()}`,label:item=>`IL: ${item.parsed.y.toFixed(2)}%`}},title:{display:true,text:'Impermanent Loss vs 50/50 HODL',color:'#e0e0e0',font:{size:13}},annotation:{annotations:botAnn}}}});
  const f0=v=>Math.round(v).toLocaleString(),f2=v=>v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const pc=v=>v>=0?'positive':'negative',ps=v=>v>=0?`+$${f0(v)}`:`-$${f0(Math.abs(v))}`;
  document.getElementById('lpSidebar').innerHTML=`
    <div class="section-title">📊 POSITION SUMMARY</div>
    <div class="row"><span class="label">Pair</span><span class="value">${pair.toUpperCase()}</span></div>
    <div class="row"><span class="label">Range</span><span class="value">${pLow} – ${pHigh} ${quote}</span></div>
    <div class="row"><span class="label">Range width</span><span class="value">${((pHigh-pLow)/pEntry*100).toFixed(1)}%</span></div>
    <div class="row"><span class="label">Entry</span><span class="value">${pEntry} ${quote}</span></div>
    <div class="row"><span class="label">Notional</span><span class="value" style="color:#64ffda">$${f0(notional)}</span></div>
    <div class="section-title">🔻 AT ${pLow} (100% ${base})</div>
    <div class="row"><span class="label">Value</span><span class="value">${fmt(vLow)}</span></div>
    <div class="row"><span class="label">${base}</span><span class="value">${ethAtLow.toFixed(4)}</span></div>
    <div class="row"><span class="label">PnL vs entry</span><span class="value ${pc(vLow-notional)}">${ps(vLow-notional)}</span></div>
    <div class="section-title">🔺 AT ${pHigh} (100% ${quote})</div>
    <div class="row"><span class="label">Value</span><span class="value">${fmt(vHigh)}</span></div>
    <div class="row"><span class="label">PnL vs entry</span><span class="value ${pc(vHigh-notional)}">${ps(vHigh-notional)}</span></div>
    <div class="section-title">💰 FEE INCOME</div>
    <div class="row"><span class="label">Fee APR</span><span class="value" style="color:#64ffda">${feeApr}%</span></div>
    <div class="row"><span class="label">Daily</span><span class="value">$${f2(dailyFees)}</span></div>
    <div class="row"><span class="label">Monthly</span><span class="value">$${f0(dailyFees*30)}</span></div>
    <div class="row"><span class="label">Yearly</span><span class="value">$${f0(dailyFees*365)}</span></div>
    <div class="section-title">⚠️ IL vs HODL</div>
    <div class="row"><span class="label">At ${pLow}</span><span class="value negative">${ps(ilHodlLow)} (${ilPctLow.toFixed(1)}%)</span></div>
    <div class="row"><span class="label">Offset</span><span class="value">${daysLow.toFixed(1)} days</span></div>
    <div style="height:6px"></div>
    <div class="row"><span class="label">At ${pHigh}</span><span class="value negative">${ps(ilHodlHigh)} (${ilPctHigh.toFixed(1)}%)</span></div>
    <div class="row"><span class="label">Offset</span><span class="value">${daysHigh.toFixed(1)} days</span></div>
    <div style="margin-top:18px;padding:14px;background:#0a0a1a;border:1px solid #64ffda33;border-radius:8px;text-align:center;">
      <div style="color:#a8b2d1;font-size:11px;letter-spacing:1px;">⚡ BREAK-EVEN</div>
      <div class="highlight" style="margin:4px 0;">~${Math.ceil(Math.max(daysLow,daysHigh))} days</div>
      <div style="color:#a8b2d1;font-size:11px;">to cover worst-case IL</div>
    </div>`;
}
