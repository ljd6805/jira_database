Object.assign(window.JIRA_MAP_VIEWS,{
"issue":{
  "title":"Evidence Round-trip · Accepted Attempt · M10 IMPLEMENTED",
  "help":"M7의 502 canonical Evidence row를 기반으로 M10 Resolver가 ki_ → ke_ → 실제 source를 복원하고 Evidence Package로 구성합니다. MCP 2-tool 구현도 PASS했고 실제 환경 Real-run이 다음 단계입니다.",
  "nodes":[
    {"id":"issue","type":"issue","kind":"issue","shape":"pill","x":150,"y":80,"w":200,"h":62,"label":"Issue","sub":"jira_id authoritative"},
    {"id":"version","type":"issue","kind":"issue","shape":"rect","x":150,"y":245,"w":220,"h":90,"label":"Issue Version · iv_","sub":"source_hash immutable state"},
    {"id":"generation","type":"knowledge","kind":"knowledge","shape":"rect","x":440,"y":245,"w":230,"h":90,"label":"Generation · kg_","sub":"Version + Contract lineage"},
    {"id":"attempt","type":"knowledge","kind":"knowledge","shape":"rect","x":730,"y":245,"w":230,"h":90,"label":"Accepted Attempt · ka_","sub":"attempt_no · PASS"},
    {"id":"item","type":"knowledge","kind":"knowledge","shape":"rect","x":1020,"y":245,"w":230,"h":90,"label":"Knowledge Item · ki_","sub":"statement + evidence refs"},
    {"id":"eref","type":"evidence","kind":"evidence","shape":"rect","x":1150,"y":430,"w":230,"h":90,"label":"Evidence · ke_","sub":"502 canonical exact refs"},
    {"id":"resolver","type":"db","kind":"db","shape":"rect","x":920,"y":590,"w":250,"h":90,"label":"M10 Resolver · PASS","sub":"6-type source lookup"},
    {"id":"source","type":"evidence","kind":"evidence","shape":"rect","x":620,"y":590,"w":250,"h":90,"label":"Resolved Source","sub":"version / comment / attachment / edge / field"},
    {"id":"raw","type":"store","kind":"store","shape":"rect","x":320,"y":590,"w":240,"h":90,"label":"ANALYSIS → RAW","sub":"internal source provenance"},
    {"id":"review","type":"review","kind":"review","shape":"rect","x":1160,"y":760,"w":210,"h":80,"label":"Review Audit","sub":"Attempt별 verdict / finding"}
  ],
  "edges":[
    {"from":"issue","to":"version","label":"1:N versions","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"generation","label":"1:N","fromSide":"right","toSide":"left"},
    {"from":"generation","to":"attempt","label":"accepted_attempt_id","fromSide":"right","toSide":"left"},
    {"from":"attempt","to":"item","label":"1:N items","fromSide":"right","toSide":"left"},
    {"from":"item","to":"eref","label":"1:N refs","fromSide":"bottom","toSide":"top"},
    {"from":"eref","to":"resolver","label":"parse type / key","fromSide":"left","toSide":"top"},
    {"from":"resolver","to":"source","label":"exact lookup","fromSide":"left","toSide":"right"},
    {"from":"source","to":"raw","label":"internal provenance","fromSide":"left","toSide":"right"},
    {"from":"attempt","to":"review","label":"0..1 review","fromSide":"bottom","toSide":"top"}
  ]
},
"schema":{
  "title":"M7 SQLite → M8 Embedding → M9 Retrieval → M10 Evidence/MCP",
  "help":"M7 SQLite, M8 BGE-M3, M9 FAISS retrieval은 모두 실데이터 PASS했고 M10의 ki_/ke_ Evidence resolve와 MCP 2-tool 구현도 PASS했습니다. M10-05 실제 환경 Real-run이 남았습니다.",
  "nodes":[
    {"id":"run","type":"db","kind":"db","shape":"rect","x":115,"y":80,"w":200,"h":82,"label":"pipeline_run","sub":"run_id"},
    {"id":"issue","type":"issue","kind":"issue","shape":"rect","x":365,"y":80,"w":210,"h":82,"label":"issue","sub":"jira_id PK · issue_key locator"},
    {"id":"version","type":"issue","kind":"issue","shape":"rect","x":365,"y":245,"w":230,"h":88,"label":"issue_version","sub":"UNIQUE(jira_id, source_hash)"},
    {"id":"obs","type":"db","kind":"db","shape":"rect","x":115,"y":245,"w":220,"h":88,"label":"issue_version_observation","sub":"PK(run_id, jira_id)"},
    {"id":"generation","type":"knowledge","kind":"knowledge","shape":"rect","x":660,"y":80,"w":235,"h":88,"label":"knowledge_generation","sub":"kg_ · state · accepted_attempt_id"},
    {"id":"attempt","type":"knowledge","kind":"knowledge","shape":"rect","x":935,"y":80,"w":235,"h":88,"label":"knowledge_attempt","sub":"ka_ · attempt_no · content hash"},
    {"id":"item","type":"knowledge","kind":"knowledge","shape":"rect","x":1190,"y":245,"w":220,"h":88,"label":"knowledge_item","sub":"285 · ki_ · category · ordinal"},
    {"id":"evidence","type":"evidence","kind":"evidence","shape":"rect","x":1190,"y":430,"w":220,"h":88,"label":"knowledge_evidence","sub":"502 canonical · exact ref"},
    {"id":"review","type":"review","kind":"review","shape":"rect","x":900,"y":430,"w":220,"h":88,"label":"knowledge_review","sub":"37 · UNIQUE(attempt)"},
    {"id":"finding","type":"review","kind":"review","shape":"rect","x":900,"y":610,"w":220,"h":82,"label":"review_finding","sub":"audit history"},
    {"id":"active","type":"db","kind":"db","shape":"rect","x":650,"y":790,"w":300,"h":90,"label":"Active UNIQUE Index","sub":"30 active · one per jira_id"},
    {"id":"gate","type":"store","kind":"store","shape":"rect","x":1010,"y":790,"w":300,"h":90,"label":"M7 Real-run PASS","sub":"idempotent · FK 0 · integrity OK"},
    {"id":"embedding","type":"db","kind":"db","shape":"rect","x":1120,"y":650,"w":250,"h":80,"label":"M8 Validated Embeddings","sub":"285 emb_ · 1024 dim · PASS"},
    {"id":"retrieval","type":"db","kind":"db","shape":"rect","x":650,"y":650,"w":250,"h":80,"label":"M9 Retrieval Artifact","sub":"DONE · rc_ · fi_ · real-run PASS"}
  ],
  "edges":[
    {"from":"run","to":"obs","label":"1:N","fromSide":"bottom","toSide":"top"},
    {"from":"issue","to":"version","label":"1:N versions","fromSide":"bottom","toSide":"top"},
    {"from":"version","to":"obs","label":"observed","fromSide":"left","toSide":"right"},
    {"from":"version","to":"generation","label":"1:N generations","fromSide":"right","toSide":"left"},
    {"from":"generation","to":"attempt","label":"1:N attempts","fromSide":"right","toSide":"left"},
    {"from":"attempt","to":"item","label":"1:N items","fromSide":"bottom","toSide":"top"},
    {"from":"attempt","to":"review","label":"0..1 review","fromSide":"bottom","toSide":"top"},
    {"from":"item","to":"evidence","label":"1:N refs","fromSide":"bottom","toSide":"top"},
    {"from":"review","to":"finding","label":"1:N findings","fromSide":"bottom","toSide":"top"},
    {"from":"generation","to":"active","label":"partial UNIQUE","fromSide":"bottom","toSide":"top"},
    {"from":"evidence","to":"gate","label":"round-trip PASS","fromSide":"bottom","toSide":"top"},
    {"from":"attempt","to":"gate","label":"count / idempotency PASS","fromSide":"bottom","toSide":"top"},
    {"from":"item","to":"embedding","label":"active accepted → emb_","fromSide":"bottom","toSide":"top"},
    {"from":"embedding","to":"retrieval","label":"L2 normalize + index","fromSide":"left","toSide":"right"},
    {"from":"retrieval","to":"item","label":"position → emb_ → ki_","fromSide":"top","toSide":"bottom"}
  ]
}
});