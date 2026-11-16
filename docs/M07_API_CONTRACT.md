# M07 Supply-first API contract

本文件冻结 Milestone 07 中开发者 A 与开发者 B 之间共享的 HTTP、WebSocket 和数据字段。
业务规则仍由服务层执行；前端、Agent 和客户端不得自行推导候选资格或接受结果。

## Shared conventions

- 所有 Demo 身份继续使用 `X-Demo-User-Id`。路径中的用户 ID 必须与当前身份一致。
- 时间使用带时区的 RFC 3339 字符串；服务端以 `Asia/Hong_Kong` 判断“今日”。
- 业务冲突返回 `409` 和稳定的 `code`；输入错误返回 `422`；越权返回 `403`。
- AI 与手动筛选只调用 `POST /api/helpers/search`。搜索条件来自已保存的 `HelpRequest`，不得在搜索请求中另传一套条件。
- 搜索和 WebSocket 响应不得返回 Helper 精确楼栋、完整库存、原始信誉分或无关个人资料。

## Service taxonomy and request fields

服务能力代码固定为：

- `moving`
- `printing`
- `tutoring`
- `other`

`other` 必须同时提供非空 `service_name`。物品请求的 `service_code` 和 `service_name` 为 `null`；服务请求使用 `item_type=other`。

## Helper profile

### `GET /api/demo/users/{user_id}/helper-profile`

返回：

```json
{
  "user_id": 5,
  "items": [
    {
      "id": 21,
      "item_type": "scientific_calculator",
      "item_name": "Casio fx-991CN X",
      "brand": "Casio",
      "model": "fx-991CN X",
      "active": true,
      "available": true
    }
  ],
  "services": [
    {
      "id": 8,
      "service_code": "moving",
      "service_name": "搬运实验器材",
      "active": true
    }
  ]
}
```

### `PUT /api/demo/users/{user_id}/helper-profile`

请求体与上述 `items`、`services` 数组相同，但省略只读的 `available`；新记录同时省略 `id`。这是完整快照更新：遗漏的旧记录软停用，已被历史记录引用的数据不删除。

## Daily availability

### `GET /api/demo/users/{user_id}/daily-availability`

返回今日已保存状态；若今日尚未保存，`availability` 为 `null`，并从最近一次状态提供 `suggested_item_ids` 与 `suggested_service_ids`，但不会自动开启愿意帮助。

```json
{
  "local_date": "2026-11-16",
  "availability": {
    "willing": true,
    "available_from": "2026-11-16T14:00:00+08:00",
    "available_until": "2026-11-16T18:00:00+08:00",
    "campus_building": "Z",
    "accepts_urgent": true,
    "item_ids": [21],
    "service_ids": [8]
  },
  "suggested_item_ids": [21],
  "suggested_service_ids": [8]
}
```

### `PUT /api/demo/users/{user_id}/daily-availability`

请求体为 `availability` 对象。起止时间必须属于香港本地的同一“今日”，且开始早于结束；物品和服务 ID 必须属于当前 Helper 的有效长期资料，物品还必须处于 `available=true`。昨日清单建议只包含仍属于该 Helper、未被软停用且当前可用的物品或有效服务 ID；客户端应用建议时必须再次与最新有效资料取交集。

## Deterministic Helper search

### `POST /api/helpers/search`

请求：

```json
{"request_id": 42, "limit": 5}
```

`limit` 允许 3 至 5，默认 5。只有 Requester 可以搜索自己的未完成请求。

返回：

```json
{
  "request_id": 42,
  "searched_at": "2026-11-16T12:00:00Z",
  "candidates": [
    {
      "helper_id": 5,
      "display_name": "Erin",
      "match_reason": "exact_model",
      "estimated_arrival_minutes": 6,
      "available_from": "2026-11-16T14:00:00+08:00",
      "available_until": "2026-11-16T18:00:00+08:00",
      "reliability_level": "A",
      "is_substitute": false,
      "item_name": "Casio fx-991CN X",
      "item_brand": "Casio",
      "item_model": "fx-991CN X"
    }
  ],
  "issue": null
}
```

`match_reason` 为 `exact_model | exact_brand | compatible | service_exact`。物品候选只返回本次实际匹配物品的安全名称、品牌和型号，不返回物品 ID 或 Helper 的其他库存；服务候选的三个物品字段均为 `null`。候选可达性必须同时满足预计到达时间不晚于请求截止时间且不晚于 Helper 今日可帮助结束时间，不要求可帮助结束时间覆盖整个请求截止时间。无候选时返回空数组和稳定的 request-level `issue`，不得返回被过滤的 Helper 信息。

M07 业务冲突的稳定 `409 code` 至少包括：

- `invitation_round_open`
- `no_open_round`
- `invitation_inactive`
- `request_not_searchable`
- `substitute_not_allowed`
- `candidates_stale`
- `already_claimed`

## Invitation rounds

### `POST /api/requests/{request_id}/invitations`

请求：`{"helper_ids":[5,7]}`。每轮 1 至 3 个唯一 Helper。服务端在同一事务内重新匹配全部选择；任一候选失效时整批失败：

```json
{"detail":"候选状态已变化，请重新搜索。","code":"candidates_stale"}
```

成功后请求进入 `awaiting_response`，但不会发布到旧的公开 Helper Board。

### `GET /api/requests/{request_id}/invitations`

Requester 查看当前轮次和历史邀请。

### `POST /api/requests/{request_id}/invitations/close`

关闭当前轮次，取消该轮所有 `pending` 或 `proposed` 邀请，并让请求从 `awaiting_response` 回到 `searching`。同一 request ID 可以随后开启新轮次。

### `GET /api/helpers/{helper_id}/invitations`

仅本人可读取。返回 `pending`、`active` 和 `history` 三个数组。每项只包含该 Helper 自己获邀所需的请求、`request_item_type`、候选物品或服务及状态。替代物品下拉框必须取 Helper 私有资料中 `active=true`、`available=true`、属于今日 `item_ids` 且类型等于 `request_item_type` 的交集。

### Invitation actions

- `POST /api/invitations/{invitation_id}/accept`
- `POST /api/invitations/{invitation_id}/decline`，body 为 `{"reason":"declined"}` 或 `{"reason":"cannot_arrive"}`
- `POST /api/invitations/{invitation_id}/propose-substitute`，body 为 `{"item_id":23,"note":"可提供同类型号"}`
- `POST /api/invitations/{invitation_id}/accept-substitute`
- `POST /api/invitations/{invitation_id}/decline-substitute`

Requester 邀请搜索结果中的兼容物品候选即表示同意该候选物品；Helper 改提另一件物品时，`ask_before_substitute` 仍需 Requester 明确接受。

第一名通过事务内重新校验并接受的人创建唯一 `accepted` HelpOffer。其他邀请自动关闭；并发失败返回 `409 already_claimed`。邀请不设独立超时，随请求截止时间过期。

## Realtime

### `WS /ws/helpers/{helper_id}/invitations?demo_user_id={helper_id}`

只发送失效通知：

```json
{
  "version": 1,
  "event_id": 101,
  "event_type": "invitations_changed",
  "resource_kind": "invitation",
  "resource_id": 5,
  "status": "changed",
  "public_message": "邀请状态已更新",
  "created_at": "2026-11-16T12:00:00Z"
}
```

客户端采用 GET → 建立 WebSocket → 再 GET；断线后每两秒轮询。任何 WebSocket 消息都不是业务命令。

## Frontend ownership

- B 导出 `TodayStatusPanel` 和 `InvitationInboxPanel`，组件只接收 `actorId`。
- A 负责 `App.tsx`、底部导航、“找 Helper”、AI/Requester 页面和三个页签的最终装配。
- B 不修改 A 独占文件；A 不更改本契约字段，确需变更时先在集成分支更新本文件。
