const palette={
  issue:'#67b2ff',
  comment:'#8fe388',
  attach:'#f6c177',
  rel:'#c79af0',
  custom:'#ff99b1',
  knowledge:'#9fa8ff',
  evidence:'#61d6b5',
  review:'#ff9f80',
  db:'#64d3ff',
  store:'#7ee0e7',
  plan:'#ffcf70'
};
const groupColors=palette;
let currentView='entity';
const visibleGroups={
  issue:true,
  comment:true,
  attach:true,
  rel:true,
  custom:true,
  knowledge:true,
  evidence:true,
  review:true,
  db:true
};

function svgEl(name,attrs={},parent){
  const el=document.createElementNS('http://www.w3.org/2000/svg',name);
  Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));
  if(parent)parent.appendChild(el);
  return el;
}
function getPort(n,side='right'){
  const hw=n.w/2,hh=n.h/2;
  return {left:[n.x-hw,n.y],right:[n.x+hw,n.y],top:[n.x,n.y-hh],bottom:[n.x,n.y+hh]}[side]||[n.x,n.y];
}
function control(p,side,d){
  return {left:[p[0]-d,p[1]],right:[p[0]+d,p[1]],top:[p[0],p[1]-d],bottom:[p[0],p[1]+d]}[side]||p;
}
function pathForEdge(from,to,e){
  const start=e.fromPoint||getPort(from,e.fromSide||'right');
  const end=e.toPoint||getPort(to,e.toSide||'left');
  const dx=Math.abs(end[0]-start[0]),dy=Math.abs(end[1]-start[1]);
  const bend=Math.max(70,Math.min(190,Math.max(dx,dy)*.35));
  const c1=e.c1||control(start,e.fromSide||'right',bend);
  const c2=e.c2||control(end,e.toSide||'left',bend);
  if(e.via){
    const c3=e.c3||control(e.via,'left',bend*.6);
    const c4=e.c4||control(end,e.toSide||'left',bend);
    return {
      d:`M ${start[0]} ${start[1]} C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${e.via[0]} ${e.via[1]} C ${c3[0]} ${c3[1]}, ${c4[0]} ${c4[1]}, ${end[0]} ${end[1]}`,
      start,end,c1,c2
    };
  }
  return {d:`M ${start[0]} ${start[1]} C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${end[0]} ${end[1]}`,start,end,c1,c2};
}
function bezierMid(p0,p1,p2,p3,t=.5){
  const m=1-t;
  return [
    m*m*m*p0[0]+3*m*m*t*p1[0]+3*m*t*t*p2[0]+t*t*t*p3[0],
    m*m*m*p0[1]+3*m*m*t*p1[1]+3*m*t*t*p2[1]+t*t*t*p3[1]
  ];
}
function createNode(svg,n){
  const g=svgEl('g',{
    class:'node',
    transform:`translate(${n.x},${n.y})`,
    'data-id':n.id,
    'data-group':n.kind
  },svg);
  const c=groupColors[n.type]||'#999';
  svgEl('rect',{
    x:-n.w/2,y:-n.h/2,width:n.w,height:n.h,
    rx:n.shape==='pill'?n.h/2:18,
    fill:c+'22',
    stroke:c
  },g);
  svgEl('text',{x:0,y:-4,'text-anchor':'middle'},g).textContent=n.label;
  svgEl('text',{x:0,y:18,'text-anchor':'middle',class:'small'},g).textContent=n.sub||'';
  g.onclick=()=>showInfo(n);
}
function createEdge(svg,from,to,e){
  const {d,start,end,c1,c2}=pathForEdge(from,to,e);
  const p=e.labelPos||bezierMid(start,c1,c2,end);
  const g=svgEl('g',{class:'edge-group','data-from':e.from,'data-to':e.to},svg);
  svgEl('path',{d,class:'edge'},g);
  if(e.label){
    const w=Math.max(60,e.label.length*7.4);
    svgEl('rect',{x:p[0]-w/2,y:p[1]-12,width:w,height:22,rx:11,class:'label-tag'},g);
    svgEl('text',{x:p[0],y:p[1]+3,'text-anchor':'middle',class:'edge-label'},g).textContent=e.label;
  }
}
function showInfo(n){
  document.getElementById('infoPanel').innerHTML=
    `<div class="info-title">${n.label}</div><div class="info-body">${n.sub||'현재 데이터 구조의 구성 요소입니다.'}</div>`;
}
function groupVisible(kind){
  return kind==='store'||visibleGroups[kind]!==false;
}
function edgeVisible(v,e){
  const a=v.nodes.find(n=>n.id===e.from);
  const b=v.nodes.find(n=>n.id===e.to);
  return groupVisible(a.kind)&&groupVisible(b.kind);
}
function applyVisibility(){
  const svg=document.getElementById('networkSvg');
  const v=JIRA_MAP_VIEWS[currentView];
  svg.querySelectorAll('.node').forEach(n=>{
    n.classList.toggle('hidden',!groupVisible(n.dataset.group));
  });
  svg.querySelectorAll('.edge-group').forEach((g,i)=>{
    g.classList.toggle('hidden',!edgeVisible(v,v.edges[i]));
  });
}
function drawView(name){
  currentView=name;
  const svg=document.getElementById('networkSvg');
  const v=JIRA_MAP_VIEWS[name];
  svg.innerHTML='<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="9" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L12,6 L0,12 z" fill="rgba(216,230,255,.60)"></path></marker></defs>';
  document.getElementById('viewTitle').textContent=v.title;
  document.getElementById('viewHelp').textContent=v.help;
  const map=Object.fromEntries(v.nodes.map(n=>[n.id,n]));
  v.edges.forEach(e=>createEdge(svg,map[e.from],map[e.to],e));
  v.nodes.forEach(n=>createNode(svg,n));
  applyVisibility();
  showInfo(v.nodes[0]);
}
document.querySelectorAll('.tab').forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    drawView(b.dataset.view);
  };
});
document.querySelectorAll('.toggle').forEach(b=>{
  b.onclick=()=>{
    const k=b.dataset.group;
    visibleGroups[k]=!visibleGroups[k];
    b.classList.toggle('on',visibleGroups[k]);
    applyVisibility();
  };
});
drawView('entity');
