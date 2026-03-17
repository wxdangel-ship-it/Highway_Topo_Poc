# 鏁版嵁妯″瀷锛歊ound 1 椤圭洰鏂囨。缁撴瀯鏁存敼

## 瀹炰綋

### 项目文档实体（ProjectDocument）

- **鐢ㄩ€?*锛氳〃绀轰竴涓」鐩骇鐨勭ǔ瀹氭垨涓存椂鏂囨。銆?- **鍏抽敭灞炴€?*锛?  - `path`
  - `scope`锛坄project`銆乣workflow`銆乣historical`锛?  - `primary_attribute`锛坄source_of_truth`銆乣durable_guidance`銆乣workflow`銆乣temporary_spec`銆乣legacy_candidate`锛?  - `current_owner_surface`
  - `target_owner_surface`
  - `notes`

### 模块目录项（ModuleCatalogEntry）

- **鐢ㄩ€?*锛氳〃绀轰竴涓幇瀛樻ā鍧楋紝鎴栦竴涓渶瑕佺壒鍒爣璁扮殑 taxonomy 渚嬪銆?- **鍏抽敭灞炴€?*锛?  - `module_name`
  - `module_path`
  - `has_module_docs`
  - `has_agents`
  - `has_skill`
  - `has_src_impl`
  - `has_tests`
  - `current_status`
  - `recommended_priority`
  - `round1_action`
  - `taxonomy_notes`

### 模块文档实体（ModuleDocument）

- **鐢ㄩ€?*锛氳〃绀轰竴涓ā鍧楃骇鐨勭ǔ瀹氭垨涓存椂鏂囨。闈€?- **鍏抽敭灞炴€?*锛?  - `module_name`
  - `path`
  - `document_kind`锛坄interface_contract`銆乣agents`銆乣skill`銆乣readme`銆乣acceptance`銆乣audit`銆乣phase_note`銆乣other`锛?  - `primary_attribute`
  - `current_role`
  - `future_role`

### 架构章节（ArchitectureSection）

- **鐢ㄩ€?*锛氳〃绀轰竴涓洰鏍囨灦鏋勬枃妗ｇ珷鑺傘€?- **鍏抽敭灞炴€?*锛?  - `scope`锛坄project` 鎴?`module`锛?  - `section_id`
  - `filename`
  - `intent`
  - `source_inputs`
  - `open_questions`

### 迁移映射项（MigrationMapEntry）

- **鐢ㄩ€?*锛氳繛鎺ヤ竴涓綋鍓嶆枃妗ｆ垨鏂囨。瀹舵棌涓庢湭鏉ョ殑钀戒綅鍜屽鐞嗘柟寮忋€?- **鍏抽敭灞炴€?*锛?  - `source_path_or_family`
  - `current_attribute`
  - `target_path_or_surface`
  - `migration_action`锛坄move_later`銆乣split`銆乣keep_and_point`銆乣supersede_later`銆乣retain_as_history`锛?  - `round`
  - `rationale`

### 审核包（ReviewPackage）

- **鐢ㄩ€?*锛氬畾涔夋煇涓噸鐐瑰鏍告ā鍧楀湪 Round 1 蹇呴』鍏峰鐨勮緭鍑哄寘銆?- **鍏抽敭灞炴€?*锛?  - `module_name`
  - `research_doc_set`
  - `review_summary`
  - `required_topics`
  - `manual_questions`

## 鍏崇郴

- 涓€涓?`ModuleCatalogEntry` 瀵瑰簲澶氫釜 `ModuleDocument`銆?- 涓€涓?`ProjectDocument` 鎴?`ModuleDocument` 鍙互鏄犲皠鍒颁竴涓垨澶氫釜 `MigrationMapEntry`銆?- 姣忎釜閲嶇偣妯″潡 `ModuleCatalogEntry` 蹇呴』浜у嚭涓€涓?`ReviewPackage`銆?- 涓€涓?`ReviewPackage` 浼氬紩鐢ㄥ涓?`ArchitectureSection` 鏂囦欢銆?
## 鏍￠獙瑙勫垯

- `modules/` 涓嬫瘡涓綋鍓嶅瓨鍦ㄧ殑妯″潡鐩綍閮藉繀椤绘湁涓€涓?`ModuleCatalogEntry`銆?- 姣忎唤琚撼鍏?inventory 鐨勫叧閿枃妗ｅ繀椤讳笖鍙兘鏈変竴涓富灞炴€у垎绫汇€?- 姣忎釜閲嶇偣瀹℃牳妯″潡閮藉繀椤诲叿澶囷細
  - 涓€濂?`architecture/` 鑽夋鏂囦欢
  - 涓€浠?`review-summary.md`
- 姣忔潯杩佺Щ鏄犲皠閮藉繀椤讳繚鐣欐簮璺緞鎴栨簮鏂囨。瀹舵棌寮曠敤锛岄伩鍏嶅嚭鐜版ā绯婅縼绉汇€?
## 澶囨敞

- `t03_marking_entity` 浣滀负 taxonomy 渚嬪寤烘ā锛岃€屼笉鏄甯告ā鍧楁潯鐩紝鍥犱负瀹冨湪椤圭洰 taxonomy 涓瓨鍦ㄣ€?  浣嗗綋鍓?repo 鏍戜腑涓嶅瓨鍦ㄣ€?- `t05_topology_between_rc_v2` 浣滀负姝ｅ父妯″潡鏉＄洰寤烘ā锛屽悓鏃堕檮甯︿竴鏉℃不鐞嗗眰闈㈢殑瀹舵棌璇存槑锛?  鎸囧悜 legacy T05銆?- `t10` 浣滀负姝ｅ父妯″潡鏉＄洰寤烘ā锛屽悓鏃堕檮甯﹀懡鍚嶆紓绉昏鏄庯紝鍥犱负 `modules/` 涓?`src/` 浣跨敤浜嗕笉鍚屾爣璇嗐€?
