window.JIRA_MAP_VIEWS={
"entity":{
  "title":"Current Knowledge Entity Map · M7",
  "help":"M6-02의 authoritative 구조를 M7 SQLite 구현 기준으로 보여줍니다. Knowledge Item과 Review는 Generation에 직접 붙지 않고 Knowledge Attempt에 연결됩니다.",
  "nodes":[
    {"id":"run","type":"store","kind":"store","shape":"pill","x":120,"y":70,"w":180,"h":60,"label":"Pipeline Run","sub":"observation scope"},
    {"id":"issue","type":"issue","kind":"issue","shape":"pill","x":400,"y":70,"w":200,"h":60,"label":"Issue","sub":"jira_id authoritative"},
    {"id":"version","type":"issue","kind":"issue","shape":"rect","x":240,"y":230,"w":220,"h":90,"label":"Issue Version · iv_","sub":"jira_id + source_hash"},
    {"id":"obs","type":"db","kind":"db","shape":"rect","x":120,"y":390,"w":220,"h":86,"label":"Version Observation","sub":"run_id + jira_id"},
    {"id":"comment","type":"comment","kind":"comment","shape":"rect","x":390,"y":390,"w":190,"h":86,"label":"Comment","sub":"278 · source entity"},
    {"id":"attach","type":"attach","kind":"attach","shape":"rect","x":620,"y":390,"w":190,"h":86,"label":"Attachment","sub":"79 metadata"},
    {"id":"rel","type":"rel","kind":"rel","shape":"rect","x":850,"y":390,"w":200,"h":86,"label":"Relationship","sub":"6 canonical edges"},
    {"id":"custom","type":"custom","kind":"custom","shape":"rect","x":1090,"y":390,"w":210,"h":86,"label":"Custom Field","sub":"220 defs / 447 values"},
    {"id":"contract","type":"db","kind":"db","shape":"rect","x":540,"y":210,"w":220,"h":90,"label":"Knowledge Contract · kc_","sub":"schema · skill · runtime · model"},
    {"id":"generation","type":"knowledge","kind":"knowledge","shape":"rect","x":790,"y":210,"w":230,"h":90,"label":"Generation · kg_","sub":"Version + Contract lineage"},
    {"id":"attempt","type":"knowledge","kind":"knowledge","shape":"rect","x":1030,"y":210,"w":230,"h":90,"label":"Attempt · ka_","sub":"kg_ + attempt_no"},
    {"id":"item","type":"knowledge","kind":"knowledge","shape":"rect","x":920,"y":590,"w":220,"h":88,"label":"Knowledge Item · ki_","sub":"285 · attempt/category/ordinal"},
    {"id":"evidence","type":"evidence","kind":"evidence","shape":"rect","x":1160,"y":590,"w":220,"h":88,"label":"Evidence · ke_","sub":"503 exact refs"},
    {"id":"review","type":"review","kind":"review","shape":"rect","x":660,"y":590,"w":220,"h":88,"label":"Knowledge Review","sub":"Attempt별 verdict / score"},
    {"id":"finding","type":"review","kind":"review","shape":"rect","x":660,"y":760,"w":220,"h":82,"label":"Review Finding","sub":"audit / critical / major"},
    {"id":"sqlite","type":"db","kind":"db","shape":"rect","x":990,"y":780,"w":280,"h":88,"label":"M7 SQLite Schema v1","sub":"implemented · real-run pending"}
  ],
  "edges":[
    {"from":"run","to":"obs","label":"records","fromSide":"bottom","toSide":"top"},
    {"from":"issue","to":"version","label":"1:N versions","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"obs","label":"observed in run","fromSide":"left","toSide":"top"},
    {"from":"version","to":"generation","label":"1:N","fromSide":"right","toSide":"left"},
    {"from":"contract","to":"generation","label":"identity input","fromSide":"right","toSide":"left"},
    {"from":"generation","to":"attempt","label":"1:N retries","fromSide":"right","toSide":"left"},
    {"from":"attempt","to":"item","label":"1:N","fromSide":"bottom","toSide":"top"},
    {"from":"attempt","to":"review","label":"0..1 review","fromSide":"bottom","toSide":"top"},
    {"from":"item","to":"evidence","label":"1:N refs","fromSide":"right","toSide":"left"},
    {"from":"review","to":"finding","label":"1:N","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"comment","label":"source_run","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"attach","label":"source_run","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"rel","label":"source_run","fromSide":"right","toSide":"top"},
    {"from":"version","to":"custom","label":"source_run","fromSide":"right","toSide":"top"},
    {"from":"evidence","to":"comment","label":"type resolver","fromSide":"left","toSide":"right","c1":[1050,650],"c2":[500,500]},
    {"from":"evidence","to":"rel","label":"resolver","fromSide":"left","toSide":"bottom"},
    {"from":"attempt","to":"sqlite","label":"materialize lineage","fromSide":"bottom","toSide":"top"},
    {"from":"evidence","to":"sqlite","label":"integrity","fromSide":"bottom","toSide":"top"},
    {"from":"finding","to":"sqlite","label":"audit history","fromSide":"right","toSide":"left"}
  ]
},
"pipeline":{
  "title":"Milestone Pipeline · M0~M10",
  "help":"M0~M6는 완료했습니다. M7 코드와 synthetic integration Gate는 통과했고, 실제 30건 materialization 검증만 남았습니다. M8은 그 전까지 차단합니다.",
  "nodes":[
    {"id":"m0","type":"store","kind":"store","shape":"rect","x":110,"y":120,"w":175,"h":80,"label":"M0 DONE","sub":"RAW + ANALYSIS"},
    {"id":"m1","type":"store","kind":"store","shape":"rect","x":325,"y":120,"w":175,"h":80,"label":"M1 DONE","sub":"Knowledge Input"},
    {"id":"m2","type":"knowledge","kind":"knowledge","shape":"rect","x":540,"y":120,"w":175,"h":80,"label":"M2 DONE","sub":"Schema + Skill"},
    {"id":"m3","type":"review","kind":"review","shape":"rect","x":755,"y":120,"w":175,"h":80,"label":"M3 DONE","sub":"Quality Loop"},
    {"id":"m4","type":"knowledge","kind":"knowledge","shape":"rect","x":970,"y":120,"w":175,"h":80,"label":"M4 DONE","sub":"30/30 PASS"},
    {"id":"m5","type":"evidence","kind":"evidence","shape":"rect","x":1180,"y":120,"w":175,"h":80,"label":"M5 DONE","sub":"285 / 503 / 37"},
    {"id":"m6","type":"db","kind":"db","shape":"rect","x":1100,"y":340,"w":190,"h":84,"label":"M6 DONE","sub":"Version · ID · Attempt"},
    {"id":"m7","type":"db","kind":"db","shape":"rect","x":850,"y":340,"w":220,"h":92,"label":"M7 CURRENT","sub":"implemented · real-run pending"},
    {"id":"m8","type":"plan","kind":"store","shape":"rect","x":590,"y":340,"w":190,"h":84,"label":"M8 BLOCKED","sub":"Chunk · BGE-M3"},
    {"id":"m9","type":"plan","kind":"store","shape":"rect","x":350,"y":340,"w":190,"h":84,"label":"M9 PLAN","sub":"FAISS · Retrieval"},
    {"id":"m10","type":"plan","kind":"store","shape":"rect","x":110,"y":340,"w":190,"h":84,"label":"M10 GATE","sub":"Evidence · MCP"},
    {"id":"gate","type":"issue","kind":"issue","shape":"rect","x":850,"y":600,"w":330,"h":100,"label":"M7 Real-run Gate","sub":"30 / 30 / 37 / 285 / 503 / 37"}
  ],
  "edges":[
    {"from":"m0","to":"m1","label":"facts","fromSide":"right","toSide":"left"},
    {"from":"m1","to":"m2","label":"packages","fromSide":"right","toSide":"left"},
    {"from":"m2","to":"m3","label":"quality contract","fromSide":"right","toSide":"left"},
    {"from":"m3","to":"m4","label":"real pilot","fromSide":"right","toSide":"left"},
    {"from":"m4","to":"m5","label":"profile","fromSide":"right","toSide":"left"},
    {"from":"m5","to":"m6","label":"design evidence","fromSide":"bottom","toSide":"top"},
    {"from":"m6","to":"m7","label":"logical → physical","fromSide":"left","toSide":"right"},
    {"from":"m7","to":"m8","label":"after Gate","fromSide":"left","toSide":"right"},
    {"from":"m8","to":"m9","label":"vectors","fromSide":"left","toSide":"right"},
    {"from":"m9","to":"m10","label":"retrieval","fromSide":"left","toSide":"right"},
    {"from":"m7","to":"gate","label":"validate actual data","fromSide":"bottom","toSide":"top"}
  ]
}
};
