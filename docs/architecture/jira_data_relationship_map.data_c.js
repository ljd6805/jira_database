Object.assign(window.JIRA_MAP_VIEWS,{
  "state":{
    "title":"Operational State DB v3 · 2-Loop / Latest-Only",
    "help":"현재 FROZEN DDL v3의 핵심 5개 Operational table을 FK와 claim 조건 중심으로 보여줍니다. 점선 logical 관계가 아니라 이 화면의 연결은 모두 collector.db 내부 관계/운영 의존성입니다.",
    "nodes":[
      {"id":"sr","type":"db","kind":"db","shape":"rect","x":150,"y":110,"w":235,"h":92,"label":"source_sync_run","sub":"PK source_run_id · Loop A run","detail":"Loop A 한 번의 전체 Source Sync 실행. fixed upper, discovery/source/run status를 기록합니다."},
      {"id":"ps","type":"issue","kind":"issue","shape":"rect","x":480,"y":110,"w":235,"h":92,"label":"project_state","sub":"PK project_id · watermark","detail":"프로젝트 장기 상태. current key/name, visibility, committed_watermark와 마지막 Source 성공을 기억합니다."},
      {"id":"spr","type":"db","kind":"db","shape":"rect","x":480,"y":340,"w":255,"h":98,"label":"source_project_run","sub":"PK (source_run_id, project_id)","detail":"특정 Source Run 안에서 특정 Project를 어디까지 읽었는지 기록합니다. lower/upper, cursor, candidate/new/changed/unchanged count가 핵심입니다."},
      {"id":"work","type":"plan","kind":"db","shape":"rect","x":825,"y":340,"w":275,"h":104,"label":"sync_issue_change","sub":"PK work_item_id · durable backlog","detail":"Loop A와 Loop B 사이의 Work Item table. Source lineage, Ready Gate, latest-only supersede, knowledge/embedding/publish stage를 한 row에 기록합니다."},
      {"id":"pr","type":"knowledge","kind":"knowledge","shape":"rect","x":1140,"y":110,"w":235,"h":92,"label":"processing_run","sub":"PK processing_run_id · Loop B run","detail":"Loop B 한 번의 backlog 소비 실행. selected/published/failed/superseded count와 backlog 전후를 기록합니다."},
      {"id":"gate","type":"store","kind":"store","shape":"rect","x":825,"y":610,"w":300,"h":118,"label":"Source Ready + Latest Gate","sub":"claimable Work만 통과","detail":"committed run과 observed run이 같고, work_status가 pending/failed이며 superseded되지 않은 row만 Loop B가 claim할 수 있습니다."},
      {"id":"migration","type":"store","kind":"store","shape":"rect","x":180,"y":610,"w":260,"h":92,"label":"state_schema_migration","sub":"technical metadata · user_version=3","detail":"Operational domain이 아닌 migration audit table. schema upgrade의 from/to version, fingerprint, backup을 기록합니다."}
    ],
    "edges":[
      {"from":"sr","to":"ps","label":"FK ×3 · seen/success run","fromSide":"right","toSide":"left"},
      {"from":"sr","to":"spr","label":"FK source_run_id","fromSide":"bottom","toSide":"left"},
      {"from":"ps","to":"spr","label":"FK project_id","fromSide":"bottom","toSide":"top"},
      {"from":"ps","to":"work","label":"FK project_id","fromSide":"right","toSide":"left"},
      {"from":"sr","to":"work","label":"FK source lineage ×3","fromSide":"bottom","toSide":"top"},
      {"from":"work","to":"pr","label":"FK last_processing_run_id","fromSide":"right","toSide":"bottom"},
      {"from":"spr","to":"gate","label":"source_committed","fromSide":"right","toSide":"left"},
      {"from":"ps","to":"gate","label":"watermark same TX","fromSide":"bottom","toSide":"left"},
      {"from":"work","to":"gate","label":"ready + latest condition","fromSide":"bottom","toSide":"top"}
    ]
  },
  "crossdb":{
    "title":"State DB ↔ Knowledge DB · Physical FK vs Logical Reference",
    "help":"두 SQLite DB 사이에는 일반 FK를 걸지 않습니다. sync_issue_change의 issue_version_id / knowledge_generation_id는 Knowledge DB의 ID를 가리키는 logical reference이며, jira_id + source_hash가 reconciliation의 핵심 의미 키입니다.",
    "nodes":[
      {"id":"pr2","type":"knowledge","kind":"knowledge","shape":"rect","x":170,"y":105,"w":230,"h":86,"label":"processing_run","sub":"State DB · pr_","detail":"Loop B 실행 자체의 운영 상태입니다."},
      {"id":"work2","type":"plan","kind":"db","shape":"rect","x":235,"y":330,"w":290,"h":112,"label":"sync_issue_change","sub":"State DB · sw_ backlog","detail":"jira_id/source_hash와 Knowledge DB logical IDs를 보관합니다. DB를 넘는 물리 FK는 아닙니다."},
      {"id":"issue2","type":"issue","kind":"issue","shape":"rect","x":620,"y":105,"w":220,"h":86,"label":"issue","sub":"Knowledge DB · jira_id PK","detail":"Jira Issue의 장기 identity. issue_key는 human-readable locator입니다."},
      {"id":"iv2","type":"issue","kind":"issue","shape":"rect","x":620,"y":330,"w":250,"h":96,"label":"issue_version","sub":"iv_ · UNIQUE(jira_id, source_hash)","detail":"Jira 의미 상태의 immutable version. 같은 hash가 재등장하면 같은 Version을 재사용합니다."},
      {"id":"kg2","type":"knowledge","kind":"knowledge","shape":"rect","x":925,"y":330,"w":255,"h":96,"label":"knowledge_generation","sub":"kg_ · Version + contract","detail":"같은 Issue Version이라도 extraction contract가 달라지면 새 Generation이 가능합니다."},
      {"id":"ka2","type":"knowledge","kind":"knowledge","shape":"rect","x":1180,"y":330,"w":220,"h":90,"label":"knowledge_attempt","sub":"ka_ · retry lineage","detail":"Generation 안의 실제 생성/검증/리뷰 시도 단위입니다."},
      {"id":"ki2","type":"knowledge","kind":"knowledge","shape":"rect","x":1120,"y":555,"w":230,"h":90,"label":"knowledge_item","sub":"ki_ · searchable statement","detail":"최종 지식 문장 단위. M8 embedding corpus의 기본 단위입니다."},
      {"id":"ke2","type":"evidence","kind":"evidence","shape":"rect","x":835,"y":730,"w":235,"h":90,"label":"knowledge_evidence","sub":"ke_ · exact source ref","detail":"Knowledge Item이 어떤 Jira 원문을 근거로 하는지 exact evidence_ref로 보존합니다."},
      {"id":"source2","type":"store","kind":"store","shape":"rect","x":510,"y":730,"w":255,"h":100,"label":"Source Entity tables","sub":"version/comment/attach/rel/custom","detail":"Evidence type에 따라 issue_version 또는 run-scoped source table로 resolve됩니다."}
    ],
    "edges":[
      {"from":"work2","to":"pr2","label":"FK last_processing_run_id","fromSide":"top","toSide":"bottom"},
      {"from":"issue2","to":"iv2","label":"FK jira_id · 1:N","fromSide":"bottom","toSide":"top"},
      {"from":"iv2","to":"kg2","label":"FK issue_version_id · 1:N","fromSide":"right","toSide":"left"},
      {"from":"kg2","to":"ka2","label":"FK generation_id · 1:N","fromSide":"right","toSide":"left"},
      {"from":"ka2","to":"ki2","label":"FK attempt_id · 1:N","fromSide":"bottom","toSide":"top"},
      {"from":"ki2","to":"ke2","label":"FK item_id · 1:N","fromSide":"left","toSide":"right"},
      {"from":"ke2","to":"source2","label":"type-specific resolver","fromSide":"left","toSide":"right"},
      {"from":"work2","to":"iv2","label":"LOGICAL issue_version_id","style":"logical","fromSide":"right","toSide":"left"},
      {"from":"work2","to":"kg2","label":"LOGICAL knowledge_generation_id","style":"logical","fromSide":"right","toSide":"left"}
    ]
  }
});