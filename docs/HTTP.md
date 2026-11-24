# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

运行报告含 `scope`（本次已签范围：`items` 已签记录、`blocked` 被阻断记录、`cases` 每组已签/结转/冲突计数、`cutoff` 水位）、`pending`（`items` 待处理记录，`source` 为 `CARRY` 结转或 `BLOCK` 阻断，`carried` 与 `blocking_count` 计数）和 `handover`（`decision` 取 `SIGN_NOW_COMPLETE`、`SIGN_NOW_CARRY` 或 `BLOCKED`，附 `note`）。`GET /api/runs/<id>` 另返回 `prior`，即同一批业务分组更早批次的签收结果。同字节重跑返回同一批次，不会追加待处理记录。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。存在阻断记录时不能签发；仅有结转事件时可以按时签发。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。
