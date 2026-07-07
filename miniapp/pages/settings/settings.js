const PRESETS = [
  { name: 'DeepSeek', model: 'deepseek-chat', baseUrl: 'https://api.deepseek.com' },
  { name: 'OpenAI GPT-4o', model: 'gpt-4o', baseUrl: 'https://api.openai.com/v1' },
  { name: '通义千问', model: 'qwen-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { name: '智谱 GLM-4', model: 'glm-4', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
  { name: 'Moonshot Kimi', model: 'moonshot-v1-8k', baseUrl: 'https://api.moonshot.cn/v1' },
  { name: '自定义', model: '', baseUrl: '' },
];

Page({
  data: {
    presets: PRESETS,
    selectedIdx: 0,
    apiKey: '',
    baseUrl: '',
    model: '',
    customName: '',
  },

  onLoad() {
    const saved = wx.getStorageSync('llmSettings') || {};
    const idx = saved.presetIdx != null ? saved.presetIdx : 0;
    this.setData({
      selectedIdx: idx,
      apiKey: saved.apiKey || '',
      baseUrl: saved.baseUrl || PRESETS[idx].baseUrl,
      model: saved.model || PRESETS[idx].model,
      customName: saved.customName || '',
    });
  },

  selectPreset(e) {
    const idx = e.currentTarget.dataset.idx;
    const p = PRESETS[idx];
    this.setData({
      selectedIdx: idx,
      baseUrl: p.baseUrl,
      model: p.model,
    });
  },

  onApiKeyInput(e) { this.setData({ apiKey: e.detail.value }); },
  onBaseUrlInput(e) { this.setData({ baseUrl: e.detail.value }); },
  onModelInput(e) { this.setData({ model: e.detail.value }); },
  onCustomNameInput(e) { this.setData({ customName: e.detail.value }); },

  save() {
    const { apiKey, baseUrl, model, selectedIdx, customName } = this.data;
    if (!apiKey.trim()) {
      wx.showToast({ title: '请填写 API Key', icon: 'none' });
      return;
    }
    if (!baseUrl.trim() || !model.trim()) {
      wx.showToast({ title: '请填写完整配置', icon: 'none' });
      return;
    }
    const settings = { apiKey, baseUrl, model, presetIdx: selectedIdx, customName };
    wx.setStorageSync('llmSettings', settings);
    wx.showToast({ title: '保存成功', icon: 'success' });
    setTimeout(() => wx.navigateBack(), 800);
  },

  clear() {
    wx.removeStorageSync('llmSettings');
    this.setData({
      selectedIdx: 0,
      apiKey: '',
      baseUrl: PRESETS[0].baseUrl,
      model: PRESETS[0].model,
      customName: '',
    });
    wx.showToast({ title: '已清除', icon: 'none' });
  },
});
