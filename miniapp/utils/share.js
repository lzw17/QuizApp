// 统一的转发/分享配置：只做「推荐小程序本身」，不携带任何页面内容。
// 所有页面统一标题、统一落地首页（题库按用户隔离，落地他人具体页面也会失败）。

const APP_TITLE = '智题学习笔记 · 上传资料，AI 自动生成题库';

// 转发给好友/群聊
function shareApp() {
  return {
    title: APP_TITLE,
    path: '/pages/index/index',
  };
}

// 分享到朋友圈（单页模式，只提供标题）
function shareTimeline() {
  return {
    title: APP_TITLE,
  };
}

module.exports = { shareApp, shareTimeline };
