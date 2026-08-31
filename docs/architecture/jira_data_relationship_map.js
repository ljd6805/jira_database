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
let currentView='state';
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

function createNode(svg,n){
  const g=svgEl('g',{
    class:'node',transform:`translate(${n.x},${n.y})`,
    'data-id':n.id,'data-group':n.kind
  },svg);
  const c=groupColors[n.type]||'#999';
  svgEl('rect',{
    x:-n.w/2,y:-n.h/2,width:n.w,height:n.h,
    rx:n.shape==='pill'?n.h/2:18,fill:c+'22',stroke:c
  },g);
  svgEl('text',{x:0,y:-4,'text-anchor':'middle'},g).textContent=n.label;
  svgEl('text',{x:0,y:18,'text-anchor':'middle',class:'small'},g).textContent=n.sub||'';
  g.onclick=()=>showInfo(n);
  g.onmouseenter=()=>focusNode(n.id);
  g.onmouseleave=clearFocus;
}

function createEdgePath(svg,route,e,index){
  const g=svgEl('g',{
    class:'edge-group','data-edge-index':index,
    'data-from':e.from,'data-to':e.to
  },svg);
  const d=JiraDiagramRouter.path(route);
  svgEl('path',{d,class:'edge-halo'},g);
  const edgeClass=e.style==='logical'?'edge edge-logical':'edge';
  const path=svgEl('path',{d,class:edgeClass},g);
  if(e.label)svgEl('title',{},path).textContent=e.label;
}

function createEdgeLabel(svg,route,e,index,nodes,placed,view){
  if(!e.label)return;
  const p=JiraDiagramRouter.placeLabel(route,e.label,nodes,placed,view);
  if(!p)return;
  placed.push(p.rect);
  const g=svgEl('g',{
    class:'edge-label-group','data-edge-index':index,
    'data-from':e.from,'data-to':e.to
  },svg);
  if(p.distance>JiraDiagramRouter.settings.labelOffset*1.5){
    svgEl('line',{
      x1:p.anchor[0],y1:p.anchor[1],x2:p.x,y2:p.y,class:'edge-label-leader'
    },g);
  }
  const labelClass=e.style==='logical'?'label-tag label-tag-logical':'label-tag';
  svgEl('rect',{
    x:p.x-p.w/2,y:p.y-p.h/2,width:p.w,height:p.h,rx:12,class:labelClass
  },g);
  svgEl('text',{
    x:p.x,y:p.y+3.5,'text-anchor':'middle',class:'edge-label'
  },g).textContent=e.label;
}

function showInfo(n){
  const detail=n.detail||n.sub||'현재 데이터 구조의 구성 요소입니다.';
  document.getElementById('infoPanel').innerHTML=
    `<div class="info-title">${n.label}</div>`+
    `<div class="info-body"><div class="mono" style="display:inline-block;margin-bottom:9px">${n.sub||''}</div><br>${detail}</div>`;
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
  svg.querySelectorAll('[data-edge-index]').forEach(g=>{
    const e=v.edges[Number(g.dataset.edgeIndex)];
    g.classList.toggle('hidden',!edgeVisible(v,e));
  });
}

function focusNode(nodeId){
  const svg=document.getElementById('networkSvg');
  const connected=new Set([nodeId]);
  svg.querySelectorAll('[data-edge-index]').forEach(g=>{
    if(g.dataset.from===nodeId||g.dataset.to===nodeId){
      connected.add(g.dataset.from);
      connected.add(g.dataset.to);
      g.classList.add('focused');
    }else g.classList.add('focus-muted');
  });
  svg.querySelectorAll('.node').forEach(n=>{
    if(connected.has(n.dataset.id))n.classList.add('focused');
    else n.classList.add('focus-muted');
  });
}

function clearFocus(){
  const svg=document.getElementById('networkSvg');
  svg.querySelectorAll('.focus-muted,.focused').forEach(el=>{
    el.classList.remove('focus-muted','focused');
  });
}

function svgViewSize(svg){
  const vb=svg.viewBox.baseVal;
  return {w:vb&&vb.width?vb.width:1320,h:vb&&vb.height?vb.height:920};
}

function drawView(name){
  currentView=name;
  const svg=document.getElementById('networkSvg');
  const v=JIRA_MAP_VIEWS[name];
  if(!v)return;
  svg.innerHTML='<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L12,6 L0,12 z" fill="rgba(216,230,255,.74)"></path></marker></defs>';
  document.getElementById('viewTitle').textContent=v.title;
  document.getElementById('viewHelp').textContent=v.help;
  const view=svgViewSize(svg),placed=[];
  const routes=JiraDiagramRouter.routeEdges(v.nodes,v.edges,view);
  const edgeLayer=svgEl('g',{class:'edge-layer'},svg);
  const labelLayer=svgEl('g',{class:'edge-label-layer'},svg);
  const nodeLayer=svgEl('g',{class:'node-layer'},svg);
  v.edges.forEach((e,index)=>createEdgePath(edgeLayer,routes[index],e,index));
  v.edges.forEach((e,index)=>createEdgeLabel(labelLayer,routes[index],e,index,v.nodes,placed,view));
  v.nodes.forEach(n=>createNode(nodeLayer,n));
  applyVisibility();
  showInfo(v.nodes[0]);
}

function applyFriendlyTabLabels(){
  const labels={
    state:'State DB · 현재 개정 3',
    crossdb:'State ↔ Knowledge',
    schema:'Knowledge DB · 구현 개정 1',
    issue:'Evidence Round-trip',
    entity:'Current Entity',
    pipeline:'M0~M11 Pipeline'
  };
  document.querySelectorAll('.tab').forEach(button=>{
    const label=labels[button.dataset.view];
    if(label)button.textContent=label;
  });
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

applyFriendlyTabLabels();
document.querySelectorAll('.tab').forEach(button=>{
  button.classList.toggle('active',button.dataset.view==='state');
});
drawView('state');
