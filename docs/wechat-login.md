# 微信小程序登录方案

## 结论

本项目采用微信身份与应用登录态分离的方案：小程序通过 `wx.login` 获取一次性 `code`，后端调用微信 `code2Session` 换取身份，再由后端签发本项目自己的 Bearer token。`WX_SECRET`、`openid` 和 `session_key` 都不会下发或写入小程序缓存。

应用启动时会先校验已有 token；没有 token 或 token 已失效时，自动执行一次微信静默登录。用户主动退出后会关闭自动登录，直到再次点击“微信一键登录”。

## 可自动取得的信息

| 信息 | 是否自动 | 处理方式 |
| --- | --- | --- |
| 临时 `code` | 是 | 小程序调用 `wx.login`，每个 code 只使用一次 |
| `openid` | 是 | 后端通过 `code2Session` 获取，用作本小程序内的账户身份 |
| `unionid` | 有条件 | 微信满足 UnionID 下发条件时返回；当前登录链路接收但不下发前端 |
| `session_key` | 是 | 仅在后端当前登录请求内校验和使用，不返回前端 |
| 昵称、头像 | 否 | 微信现行规则不允许静默获取；使用昵称输入组件和 `chooseAvatar` 由用户选择 |
| 手机号 | 否 | 必须由用户点击 `getPhoneNumber` 授权；本次需求未要求绑定手机号 |

因此，“自动获取并登录”指自动取得微信身份并建立应用会话，不包括绕过用户授权静默读取头像、昵称或手机号。

## 登录时序

1. 小程序启动，读取本地 `accessToken` 和用户缓存。
2. 有 token 时请求 `GET /api/auth/me`；校验成功后直接进入应用。
3. 无 token 或服务端返回 401 时，小程序自动调用 `wx.login`。
4. 小程序把 code 发送给 `POST /api/auth/login`，不发送 AppSecret。
5. 后端携带 `WX_APPID`、`WX_SECRET` 和 code 请求微信 `code2Session`。
6. 后端按 `openid` 查找或创建用户，更新最后登录时间并签发应用 token。
7. 老用户直接进入首页；新用户进入资料完善页，可选择微信头像并填写微信昵称，也可以跳过。
8. 后续接口统一携带 `Authorization: Bearer <token>`；遇到 401 时自动重新登录并只重试一次原请求。

## 接口约定

`POST /api/auth/login` 请求：

```json
{ "code": "wx.login 返回的一次性 code" }
```

响应只包含应用会话，不包含微信敏感字段：

```json
{
  "user": { "id": 1, "nickname": "微信用户", "avatar": "", "is_admin": false },
  "is_new": true,
  "access_token": "应用 JWT",
  "token_type": "Bearer",
  "expires_in": 2592000
}
```

## 上线配置

- 在微信公众平台配置服务器 request 合法域名，必须使用已备案的 HTTPS 域名。
- 后端 `.env` 配置与小程序一致的 `WX_APPID` 和 `WX_SECRET`；AppSecret 只能存放在服务端。
- 生产环境设置 `APP_ENV=production`、`WX_MOCK_LOGIN=false`，并使用至少 32 位随机 `SECRET_KEY`。
- 将 `miniapp/app.js` 的生产 `baseUrl` 改为实际 API 域名；开发版仍按开发者工具或局域网地址运行。
- `openid` 在不同小程序 AppID 下不同。如未来需要多个小程序或公众号合并账户，应持久化 `unionid` 并增加账号合并规则。

## 官方资料

- [小程序登录流程](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)
- [wx.login](https://developers.weixin.qq.com/miniprogram/dev/api/open-api/login/wx.login.html)
- [code2Session](https://developers.weixin.qq.com/miniprogram/dev/server/API/user-login/)
- [头像昵称填写能力](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/userProfile.html)
