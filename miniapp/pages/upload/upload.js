const { uploadFile, request } = require('../../utils/request');

Page({
  data: {
    bankName: '',
    bankCategory: '',
    bankDesc: '',
    numDirect: 3,
    numLogic: 2,
    sourceType: 'file',
    selectedFile: null,
    inputUrl: '',
    submitting: false,
  },

  onNameInput(e)     { this.setData({ bankName: e.detail.value }); },
  onCategoryInput(e) { this.setData({ bankCategory: e.detail.value }); },
  onDescInput(e)     { this.setData({ bankDesc: e.detail.value }); },
  onUrlInput(e)      { this.setData({ inputUrl: e.detail.value }); },

  switchSource(e) { this.setData({ sourceType: e.currentTarget.dataset.type, selectedFile: null, inputUrl: '' }); },

  incDirect() { if (this.data.numDirect < 8) this.setData({ numDirect: this.data.numDirect + 1 }); },
  decDirect() { if (this.data.numDirect > 1) this.setData({ numDirect: this.data.numDirect - 1 }); },
  incLogic()  { if (this.data.numLogic < 8) this.setData({ numLogic: this.data.numLogic + 1 }); },
  decLogic()  { if (this.data.numLogic > 0) this.setData({ numLogic: this.data.numLogic - 1 }); },

  chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'doc', 'docx'],
      success: (res) => {
        const file = res.tempFiles[0];
        const sizeMB = (file.size / 1024 / 1024).toFixed(1);
        this.setData({
          selectedFile: {
            path: file.path,
            name: file.name,
            size: `${sizeMB} MB`,
          },
          bankName: this.data.bankName || file.name.replace(/\.(pdf|doc|docx)$/i, ''),
        });
      },
    });
  },

  removeFile() { this.setData({ selectedFile: null }); },

  async submit() {
    const { bankName, sourceType, selectedFile, inputUrl, bankCategory, bankDesc, numDirect, numLogic } = this.data;

    if (!bankName.trim()) {
      wx.showToast({ title: '请输入题库名称', icon: 'none' }); return;
    }
    if (sourceType === 'file' && !selectedFile) {
      wx.showToast({ title: '请选择文件', icon: 'none' }); return;
    }
    if (sourceType === 'url' && !inputUrl.trim()) {
      wx.showToast({ title: '请输入链接', icon: 'none' }); return;
    }

    this.setData({ submitting: true });

    const llm = wx.getStorageSync('llmSettings') || {};

    try {
      let result;
      if (sourceType === 'file') {
        result = await uploadFile(selectedFile.path, {
          bank_name: bankName,
          bank_description: bankDesc,
          bank_category: bankCategory,
          num_direct: numDirect,
          num_logic: numLogic,
          llm_api_key: llm.apiKey || '',
          llm_base_url: llm.baseUrl || '',
          llm_model: llm.model || '',
        });
      } else {
        result = await request({
          url: '/api/upload/url',
          method: 'POST',
          data: {
            url: inputUrl,
            bank_name: bankName,
            bank_description: bankDesc,
            bank_category: bankCategory,
            num_direct: numDirect,
            num_logic: numLogic,
            llm_api_key: llm.apiKey || '',
            llm_base_url: llm.baseUrl || '',
            llm_model: llm.model || '',
          },
        });
      }

      wx.redirectTo({
        url: `/pages/generating/generating?task_id=${result.task_id}&bank_id=${result.bank_id}&bank_name=${encodeURIComponent(bankName)}`,
      });
    } catch (err) {
      this.setData({ submitting: false });
    }
  },
});
