(function (root) {
'use strict';

const ROUTE={
  nodeClearance:7,
  portGap:10,
  corridorGap:10,
  bendPenalty:26,
  crossingPenalty:900,
  overlapPenalty:1500,
  labelGap:8,
  labelOffset:18,
  labelHeight:24,
  viewPadding:24
};

function getPort(n,side='right'){
  const hw=n.w/2,hh=n.h/2;
  return {
    left:[n.x-hw,n.y],right:[n.x+hw,n.y],
    top:[n.x,n.y-hh],bottom:[n.x,n.y+hh]
  }[side]||[n.x,n.y];
}

function offsetPoint(p,side,d){
  return {
    left:[p[0]-d,p[1]],right:[p[0]+d,p[1]],
    top:[p[0],p[1]-d],bottom:[p[0],p[1]+d]
  }[side]||p;
}

function nodeRect(n,pad=0){
  return {
    left:n.x-n.w/2-pad,
    right:n.x+n.w/2+pad,
    top:n.y-n.h/2-pad,
    bottom:n.y+n.h/2+pad
  };
}

function pointsEqual(a,b){
  return Math.abs(a[0]-b[0])<0.01&&Math.abs(a[1]-b[1])<0.01;
}

function simplifyPoints(points){
  const dedup=[];
  points.forEach(p=>{
    if(!dedup.length||!pointsEqual(dedup[dedup.length-1],p))dedup.push(p);
  });
  const out=[];
  dedup.forEach(p=>{
    while(out.length>=2){
      const a=out[out.length-2],b=out[out.length-1];
      const sameX=Math.abs(a[0]-b[0])<0.01&&Math.abs(b[0]-p[0])<0.01;
      const sameY=Math.abs(a[1]-b[1])<0.01&&Math.abs(b[1]-p[1])<0.01;
      if(!sameX&&!sameY)break;
      out.pop();
    }
    out.push(p);
  });
  return out;
}

function segmentLength(a,b){
  return Math.abs(a[0]-b[0])+Math.abs(a[1]-b[1]);
}

function segmentHitsRect(a,b,r){
  const eps=.1;
  if(Math.abs(a[1]-b[1])<eps){
    const y=a[1],lo=Math.min(a[0],b[0]),hi=Math.max(a[0],b[0]);
    return y>r.top+eps&&y<r.bottom-eps&&hi>r.left+eps&&lo<r.right-eps;
  }
  if(Math.abs(a[0]-b[0])<eps){
    const x=a[0],lo=Math.min(a[1],b[1]),hi=Math.max(a[1],b[1]);
    return x>r.left+eps&&x<r.right-eps&&hi>r.top+eps&&lo<r.bottom-eps;
  }
  return true;
}

function segmentRelation(a,b,c,d){
  const aH=Math.abs(a[1]-b[1])<.1;
  const cH=Math.abs(c[1]-d[1])<.1;
  if(aH!==cH){
    const hA=aH?a:c,hB=aH?b:d,vA=aH?c:a,vB=aH?d:b;
    const hx1=Math.min(hA[0],hB[0]),hx2=Math.max(hA[0],hB[0]);
    const vy1=Math.min(vA[1],vB[1]),vy2=Math.max(vA[1],vB[1]);
    const x=vA[0],y=hA[1];
    return x>hx1+.1&&x<hx2-.1&&y>vy1+.1&&y<vy2-.1?'cross':null;
  }
  if(aH){
    if(Math.abs(a[1]-c[1])>.1)return null;
    const overlap=Math.min(Math.max(a[0],b[0]),Math.max(c[0],d[0]))-
      Math.max(Math.min(a[0],b[0]),Math.min(c[0],d[0]));
    return overlap>4?'overlap':null;
  }
  if(Math.abs(a[0]-c[0])>.1)return null;
  const overlap=Math.min(Math.max(a[1],b[1]),Math.max(c[1],d[1]))-
    Math.max(Math.min(a[1],b[1]),Math.min(c[1],d[1]));
  return overlap>4?'overlap':null;
}

function routeSegments(points){
  const segments=[];
  for(let i=0;i<points.length-1;i++)segments.push([points[i],points[i+1]]);
  return segments;
}

function routeInteractionPenalty(a,b,existingRoutes){
  let penalty=0;
  existingRoutes.forEach(route=>{
    routeSegments(route.points).forEach(([c,d])=>{
      const relation=segmentRelation(a,b,c,d);
      if(relation==='cross')penalty+=ROUTE.crossingPenalty;
      if(relation==='overlap')penalty+=ROUTE.overlapPenalty;
    });
  });
  return penalty;
}

function pointInsideRect(p,r){
  return p[0]>r.left+.1&&p[0]<r.right-.1&&p[1]>r.top+.1&&p[1]<r.bottom-.1;
}

// 노드 외곽의 안전한 x/y corridor 후보를 만든다.
function coordinateSet(nodes,axis,startOut,endOut,view){
  const limit=axis==='x'?view.w:view.h;
  const values=[
    axis==='x'?startOut[0]:startOut[1],
    axis==='x'?endOut[0]:endOut[1],
    ROUTE.viewPadding,
    limit-ROUTE.viewPadding
  ];
  nodes.forEach(n=>{
    const r=nodeRect(n,ROUTE.nodeClearance);
    if(axis==='x')values.push(r.left-ROUTE.corridorGap,r.right+ROUTE.corridorGap);
    else values.push(r.top-ROUTE.corridorGap,r.bottom+ROUTE.corridorGap);
  });
  return [...new Set(values.map(v=>Math.round(Math.max(ROUTE.viewPadding,Math.min(limit-ROUTE.viewPadding,v))*10)/10))]
    .sort((a,b)=>a-b);
}

class MinHeap{
  constructor(){this.items=[];}
  push(item){
    const a=this.items;a.push(item);let i=a.length-1;
    while(i>0){const p=(i-1)>>1;if(a[p][0]<=item[0])break;a[i]=a[p];i=p;}
    a[i]=item;
  }
  pop(){
    const a=this.items;if(!a.length)return null;
    const root=a[0],last=a.pop();if(!a.length)return root;
    let i=0;
    while(true){
      let l=i*2+1,r=l+1;if(l>=a.length)break;
      let c=r<a.length&&a[r][0]<a[l][0]?r:l;
      if(a[c][0]>=last[0])break;a[i]=a[c];i=c;
    }
    a[i]=last;return root;
  }
  get length(){return this.items.length;}
}

function stateKey(ix,iy,dir){return `${ix}:${iy}:${dir}`;}

function segmentBlocked(a,b,obstacles){
  return obstacles.some(r=>segmentHitsRect(a,b,r));
}

function gridNeighbors(ix,iy,xs,ys,obstacles){
  const out=[];
  const dirs=[[-1,0,1],[1,0,1],[0,-1,2],[0,1,2]];
  for(const [dx,dy,dir] of dirs){
    const nx=ix+dx,ny=iy+dy;
    if(nx<0||nx>=xs.length||ny<0||ny>=ys.length)continue;
    const a=[xs[ix],ys[iy]],b=[xs[nx],ys[ny]];
    if(obstacles.some(r=>pointInsideRect(b,r)))continue;
    if(segmentBlocked(a,b,obstacles))continue;
    out.push({ix:nx,iy:ny,dir,a,b});
  }
  return out;
}

function reconstructGridPath(prev,endKey,start,startOut,endOut,end,xs,ys){
  const states=[];let key=endKey;
  while(key){states.push(key);key=prev.get(key)||null;}
  states.reverse();
  const gridPoints=states.map(k=>{
    const [ix,iy]=k.split(':').map(Number);return [xs[ix],ys[iy]];
  });
  return simplifyPoints([start,startOut,...gridPoints,endOut,end]);
}

// 방향 전환과 기존 edge 교차에 비용을 주는 Dijkstra routing.
function findGridRoute(start,startOut,endOut,end,obstacles,nodes,existingRoutes,view){
  const xs=coordinateSet(nodes,'x',startOut,endOut,view);
  const ys=coordinateSet(nodes,'y',startOut,endOut,view);
  const sx=xs.indexOf(startOut[0]),sy=ys.indexOf(startOut[1]);
  const ex=xs.indexOf(endOut[0]),ey=ys.indexOf(endOut[1]);
  const heap=new MinHeap(),dist=new Map(),prev=new Map();
  const startKey=stateKey(sx,sy,0);dist.set(startKey,0);heap.push([0,startKey]);
  let endKey=null;
  while(heap.length){
    const [cost,key]=heap.pop();if(cost!==dist.get(key))continue;
    const [ix,iy,dir]=key.split(':').map(Number);
    if(ix===ex&&iy===ey){endKey=key;break;}
    for(const n of gridNeighbors(ix,iy,xs,ys,obstacles)){
      const nextKey=stateKey(n.ix,n.iy,n.dir);
      const bend=dir&&dir!==n.dir?ROUTE.bendPenalty:0;
      const step=segmentLength(n.a,n.b)+bend+routeInteractionPenalty(n.a,n.b,existingRoutes);
      const next=cost+step;
      if(next<(dist.get(nextKey)??Number.POSITIVE_INFINITY)){
        dist.set(nextKey,next);prev.set(nextKey,key);heap.push([next,nextKey]);
      }
    }
  }
  if(!endKey)return null;
  return reconstructGridPath(prev,endKey,start,startOut,endOut,end,xs,ys);
}

function routeForEdge(from,to,e,nodes,existingRoutes,view){
  if(Array.isArray(e.route)&&e.route.length){
    return {points:simplifyPoints([getPort(from,e.fromSide||'right'),...e.route,getPort(to,e.toSide||'left')])};
  }
  const fromSide=e.fromSide||'right',toSide=e.toSide||'left';
  const start=e.fromPoint||getPort(from,fromSide);
  const end=e.toPoint||getPort(to,toSide);
  const startOut=offsetPoint(start,fromSide,ROUTE.portGap);
  const endOut=offsetPoint(end,toSide,ROUTE.portGap);
  const obstacles=nodes
    .filter(n=>n.id!==from.id&&n.id!==to.id)
    .map(n=>nodeRect(n,ROUTE.nodeClearance));
  const points=findGridRoute(start,startOut,endOut,end,obstacles,nodes,existingRoutes,view);
  if(points)return {points};
  return {points:simplifyPoints([start,startOut,[endOut[0],startOut[1]],endOut,end]),fallback:true};
}

function routePath(points){
  return points.map((p,i)=>(i?'L':'M')+` ${p[0]} ${p[1]}`).join(' ');
}

function rectOverlap(a,b,gap=0){
  return !(a.right+gap<b.left||a.left-gap>b.right||a.bottom+gap<b.top||a.top-gap>b.bottom);
}

function labelRect(x,y,w,h){
  return {left:x-w/2,right:x+w/2,top:y-h/2,bottom:y+h/2};
}

function labelWidth(text){
  return Math.max(72,Math.min(220,text.length*7.6+22));
}

function leaderClear(a,b,nodeRects){
  return !nodeRects.some(r=>segmentHitsRect(a,b,r));
}

// edge midpoint 고정 대신 빈 공간을 탐색해 label을 배치한다.
function labelPosition(route,label,nodes,placed,view){
  const w=labelWidth(label),h=ROUTE.labelHeight;
  const segments=routeSegments(route.points)
    .map(([a,b])=>({a,b,len:segmentLength(a,b),horizontal:Math.abs(a[1]-b[1])<.1}))
    .filter(s=>s.len>1)
    .sort((a,b)=>b.len-a.len);
  const nodeRects=nodes.map(n=>nodeRect(n,ROUTE.labelGap));
  const leaderRects=nodes.map(n=>nodeRect(n,0));
  const distances=[18,36,56,76,96,118];
  for(const s of segments){
    for(const t of [.5,.35,.65,.2,.8]){
      const bx=s.a[0]+(s.b[0]-s.a[0])*t;
      const by=s.a[1]+(s.b[1]-s.a[1])*t;
      for(const distance of distances){
        const offsets=s.horizontal
          ? [[0,-distance],[0,distance]]
          : [[-(w/2+distance),0],[w/2+distance,0]];
        for(const [ox,oy] of offsets){
          const x=bx+ox,y=by+oy,r=labelRect(x,y,w,h);
          const inView=r.left>=ROUTE.viewPadding&&r.right<=view.w-ROUTE.viewPadding&&
            r.top>=ROUTE.viewPadding&&r.bottom<=view.h-ROUTE.viewPadding;
          if(!inView)continue;
          if(nodeRects.some(nr=>rectOverlap(r,nr)))continue;
          if(placed.some(pr=>rectOverlap(r,pr,4)))continue;
          if(!leaderClear([bx,by],[x,y],leaderRects))continue;
          return {x,y,w,h,rect:r,anchor:[bx,by],distance};
        }
      }
    }
  }
  const anchors=[];
  routeSegments(route.points).forEach(([a,b])=>{
    anchors.push([(a[0]+b[0])/2,(a[1]+b[1])/2]);
  });
  for(const anchor of anchors){
    for(const distance of [48,72,96,124,152,184,216]){
      const offsets=[[0,-distance],[0,distance],[-(w/2+distance),0],[w/2+distance,0]];
      for(const [ox,oy] of offsets){
        const x=anchor[0]+ox,y=anchor[1]+oy,r=labelRect(x,y,w,h);
        const inView=r.left>=ROUTE.viewPadding&&r.right<=view.w-ROUTE.viewPadding&&
          r.top>=ROUTE.viewPadding&&r.bottom<=view.h-ROUTE.viewPadding;
        if(!inView)continue;
        if(nodeRects.some(nr=>rectOverlap(r,nr)))continue;
        if(placed.some(pr=>rectOverlap(r,pr,4)))continue;
        if(!leaderClear(anchor,[x,y],leaderRects))continue;
        return {x,y,w,h,rect:r,anchor,distance};
      }
    }
  }
  return null;
}

function routeEdges(nodes,edges,view){
  const map=Object.fromEntries(nodes.map(n=>[n.id,n]));
  const routes=[];
  edges.forEach(e=>{
    routes.push(routeForEdge(map[e.from],map[e.to],e,nodes,routes,view));
  });
  return routes;
}

root.JiraDiagramRouter={
  routeEdges,
  path:route=>routePath(route.points),
  placeLabel:labelPosition,
  settings:ROUTE
};
})(window);
