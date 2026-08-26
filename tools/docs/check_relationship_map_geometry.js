/*
 * Jira relationship map의 정적 geometry QA.
 * 브라우저 없이 route와 label이 node를 침범하는지 검사한다.
 */
global.window=global;
require('../../docs/architecture/jira_data_relationship_router.js');
require('../../docs/architecture/jira_data_relationship_map.data_a.js');
require('../../docs/architecture/jira_data_relationship_map.data_b.js');

function nodeRect(n,pad=0){
  return {left:n.x-n.w/2-pad,right:n.x+n.w/2+pad,top:n.y-n.h/2-pad,bottom:n.y+n.h/2+pad};
}

function segmentHitsRect(a,b,r){
  const eps=.1;
  if(Math.abs(a[1]-b[1])<eps){
    const y=a[1],lo=Math.min(a[0],b[0]),hi=Math.max(a[0],b[0]);
    return y>r.top+eps&&y<r.bottom-eps&&hi>r.left+eps&&lo<r.right-eps;
  }
  const x=a[0],lo=Math.min(a[1],b[1]),hi=Math.max(a[1],b[1]);
  return x>r.left+eps&&x<r.right-eps&&hi>r.top+eps&&lo<r.bottom-eps;
}

function routeSegments(route){
  const out=[];
  for(let i=0;i<route.points.length-1;i++)out.push([route.points[i],route.points[i+1]]);
  return out;
}

function rectOverlap(a,b,gap=0){
  return !(a.right+gap<b.left||a.left-gap>b.right||a.bottom+gap<b.top||a.top-gap>b.bottom);
}

function assert(condition,message){
  if(!condition)throw new Error(message);
}

function validateView(name,view){
  const canvas={w:1320,h:920};
  const routes=JiraDiagramRouter.routeEdges(view.nodes,view.edges,canvas);
  const placed=[];
  let labels=0;

  view.edges.forEach((edge,index)=>{
    const route=routes[index];
    assert(!route.fallback,`${name}: ${edge.from}->${edge.to} router fallback`);
    const obstacles=view.nodes.filter(n=>n.id!==edge.from&&n.id!==edge.to);
    routeSegments(route).forEach(([a,b])=>{
      obstacles.forEach(node=>{
        assert(!segmentHitsRect(a,b,nodeRect(node,0)),`${name}: ${edge.from}->${edge.to} crosses ${node.id}`);
      });
    });

    if(edge.label){
      const p=JiraDiagramRouter.placeLabel(route,edge.label,view.nodes,placed,canvas);
      assert(p,`${name}: label not placed for ${edge.from}->${edge.to}`);
      const nodeCollision=view.nodes.some(node=>rectOverlap(p.rect,nodeRect(node,0)));
      const labelCollision=placed.some(rect=>rectOverlap(p.rect,rect,0));
      assert(!nodeCollision,`${name}: label overlaps node for ${edge.from}->${edge.to}`);
      assert(!labelCollision,`${name}: label overlaps label for ${edge.from}->${edge.to}`);
      placed.push(p.rect);
      labels++;
    }
  });
  return {edges:view.edges.length,labels};
}

let edgeCount=0,labelCount=0;
Object.entries(JIRA_MAP_VIEWS).forEach(([name,view])=>{
  const result=validateView(name,view);
  edgeCount+=result.edges;
  labelCount+=result.labels;
  console.log(`PASS ${name}: edges=${result.edges}, labels=${result.labels}`);
});

assert(edgeCount===62,`unexpected edge count: ${edgeCount}`);
assert(labelCount===62,`unexpected label count: ${labelCount}`);
console.log(`PASS relationship map geometry: ${edgeCount} edges / ${labelCount} labels`);
