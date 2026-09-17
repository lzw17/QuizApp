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
    uploadProgress: 0,
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

  _formatFileSize(size) {
    if (!Number.isFinite(size)) return '大小未知';
    if (size < 1024 * 1024) return `${Math.max(1, Math.ceil(size / 1024))} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  },

  _validateSelectedFile(file) {
    if (!file || !file.path || file.sizeBytes <= 0) {
      return Promise.reject(new Error('文件为空或已失效，请重新选择'));
    }
    if (typeof wx.getFileSystemManager !== 'function') return Promise.resolve();

    const fileSystemManager = wx.getFileSystemManager();
    if (!fileSystemManager || typeof fileSystemManager.stat !== 'function') {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      fileSystemManager.stat({
        path: file.path,
        success: result => {
          const stats = result && result.stats;
          if (stats && typeof stats.size === 'number' && stats.size <= 0) {
            reject(new Error('文件为空，请重新选择'));
            return;
          }
          resolve();
        },
        fail: () => reject(new Error('所选文件已失效，请重新选择')),
      });
    });
  },

  chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'docx'],
      success: (res) => {
        const file = res.tempFiles[0];
        if (!file || !file.path || file.size <= 0) {
          wx.showToast({ title: '文件为空，请重新选择', icon: 'none' });
          return;
        }
        if (file.size > 50 * 1024 * 1024) {
          wx.showToast({ title: '文件不能超过 50MB', icon: 'none' });
          return;
        }
        this.setData({
          selectedFile: {
            path: file.path,
            name: file.name,
            size: this._formatFileSize(file.size),
            sizeBytes: file.size,
          },
            bankName: this.data.bankName || file.name.replace(/\.(pdf|docx)$/i, ''),
        });
      },
    });
  },

  removeFile() { this.setData({ selectedFile: null }); },

  async submit() {
    if (this.data.submitting) return;
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

    if (sourceType === 'file') {
      try {
        await this._validateSelectedFile(selectedFile);
      } catch (error) {
        this.setData({ selectedFile: null });
        wx.showToast({ title: error.message, icon: 'none' });
        return;
      }
    }

    this.setData({ submitting: true });

    try {
      let result;
      if (sourceType === 'file') {
        result = await uploadFile(selectedFile.path, {
          bank_name: bankName,
          bank_description: bankDesc,
          bank_category: bankCategory,
          num_direct: numDirect,
          num_logic: numLogic,
        }, {
          onProgress: progress => this.setData({ uploadProgress: progress.progress || 0 }),
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
          },
        });
      }

      wx.redirectTo({
        url: `/pages/generating/generating?task_id=${result.task_id}&bank_id=${result.bank_id}&bank_name=${encodeURIComponent(bankName)}`,
      });
    } catch (err) {
      this.setData({ submitting: false });
    } finally {
      this.setData({ uploadProgress: 0 });
    }
  },
});
