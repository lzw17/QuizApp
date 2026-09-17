# 自定义模型配置

后端通过 OpenAI 兼容的 Chat Completions 协议调用模型。密钥只允许保存在服务器的 `backend/.env`，不要写入小程序、Git、命令历史、截图或聊天记录。

## 配置示例

服务商给出的完整接口若为：

```text
https://x-hive.wienerai.com.cn:31739/v1/chat/completions
```

则 `.env` 中填写的是去掉 `/chat/completions` 后的 API 根地址：

```ini
LLM_API_KEY=<重新生成的密钥>
LLM_BASE_URL=https://x-hive.wienerai.com.cn:31739/v1
LLM_MODEL=Qwen3.8-27B
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
LLM_MAX_TOKENS=4096
```

代码也能容错处理误填的完整 `/v1/chat/completions` 地址，但配置文件仍建议使用根地址。`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 必须一起配置，防止把新密钥误发到旧服务地址。三项均未配置时才会整体回退到旧的 `DEEPSEEK_*`，因此旧部署可以平滑迁移。

## 生产安全要求

当前服务商示例最初提供的是公网 `http://` 地址。明文 HTTP 会暴露 Bearer 密钥、用户上传的资料和模型响应，不能用于正式环境。后端在 `APP_ENV=production` 时会拒绝使用 HTTP 地址。请让服务商为 `x-hive.wienerai.com.cn:31739` 提供有效的 HTTPS/TLS 访问，或由模型服务所在网络提供 HTTPS 入口并通过加密隧道连接。不要只在宝塔服务器上把 HTTPS 再转发到该公网 HTTP 地址，那样后半程仍是明文。

如需在本机做一次临时连通性验证，可在 `APP_ENV=development` 的本地 `.env` 中使用 `http://x-hive.wienerai.com.cn:31739/v1`。该例外仅用于不含敏感资料的开发测试，不能复制到线上 `.env`。

聊天、截图或终端记录中出现过的密钥应立即在服务商后台作废并重新生成。不要复用已经暴露的密钥。

服务器修改完成后执行：

```bash
chmod 600 /www/wwwroot/quizapp/backend/.env
```

然后在宝塔 Python 项目管理器中重启后端，并检查：

```bash
curl --fail https://api.quizapp.chat/health
```

最后上传一份不含敏感信息的短文档做一次出题验证，并查看后端日志是否存在模型名错误、鉴权失败、TLS 失败或超时。

## 隐私披露

上传资料会交给第三方模型服务处理。小程序隐私页和微信公众平台《用户隐私保护指引》必须与生产配置保持一致，并填写该服务商的完整工商主体名称、处理目的、数据类型和处理方式；只写模型名称不能替代实际处理方信息。

当前线上配置和小程序隐私页按 DeepSeek 披露。正式切换到 WienerAI 或其他模型服务前，必须先确认其运营主体全称和数据处理规则，更新 `miniapp/pages/privacy/privacy.wxml` 与微信后台指引，再部署新的 `LLM_*` 配置；不能只修改服务器 `.env`。
