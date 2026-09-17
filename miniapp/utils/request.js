const app = getApp();

function request(options) {
  return requireSession().then(() => _request(options, false));
}

function requireSession() {
  return app.ensureLogin({ autoLogin: false }).then(user => {
    if (!user || !app.globalData.accessToken) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 300);
      throw new Error('请先登录');
    }
    return user;
  });
}

function _request(options, retried) {
  const token = app.globalData.accessToken;
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.baseUrl}${options.url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.header || {}),
      },
      timeout: options.timeout || 15000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401 && token && !retried) {
          app.clearSession();
          wx.showToast({ title: '登录已失效，请重新登录', icon: 'none' });
          setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 300);
          reject(new Error('登录已失效，请重新登录'));
        } else {
          const msg = (res.data && res.data.detail) || `请求失败 (${res.statusCode})`;
          if (!options.silent) wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        }
      },
      fail(err) {
        if (!options.silent) wx.showToast({ title: '网络错误，请检查连接', icon: 'none' });
        reject(err);
      },
    });
  });
}

function getUserId() {
  if (app.globalData.userId) return Promise.resolve(app.globalData.userId);
  if (typeof app.ensureLogin === 'function') {
    return app.ensureLogin({ autoLogin: false }).then(user => user && user.id);
  }
  return Promise.resolve(null);
}

function describeUploadFailure(error) {
  const errMsg = String((error && error.errMsg) || '').toLowerCase();

  if (errMsg.includes('domain list') || errMsg.includes('url not in domain')) {
    return '上传域名未加入微信 uploadFile 合法域名';
  }
  if (/no such file|file not found|invalid file|read file|stat file/.test(errMsg)) {
    return '所选文件已失效，请重新选择';
  }
  if (/certificate|err_cert|ssl|tls/.test(errMsg)) {
    return '服务器 HTTPS 证书异常，请联系管理员';
  }
  if (/timeout|timed out/.test(errMsg)) {
    return '文件上传超时，请检查网络后重试';
  }
  if (/abort|connection reset|connection closed|err_connection/.test(errMsg)) {
    return '服务器连接被中止，请稍后重试';
  }
  return '文件上传失败，请检查网络后重试';
}

function buildUploadError(error) {
  const uploadError = new Error(describeUploadFailure(error));
  uploadError.errMsg = (error && error.errMsg) || '';
  uploadError.errno = error && error.errno;
  return uploadError;
}

function logUploadFailure(error) {
  const errMsg = String((error && error.errMsg) || 'unknown')
    .replace(/(?:wxfile|file|https?):\/\/\S+/gi, '[file-or-url-redacted]');
  console.error('[upload] failed', {
    errMsg,
    errno: error && error.errno,
  });
}

/** 上传文件（multipart/form-data） */
function uploadFile(filePath, formData = {}, options = {}) {
  return requireSession().then(() => _uploadFile(filePath, formData, options, false));
}

function _uploadFile(filePath, formData, options, retried) {
  const token = app.globalData.accessToken;
  return new Promise((resolve, reject) => {
    const uploadTask = wx.uploadFile({
      url: `${app.globalData.baseUrl}${options.url || '/api/upload'}`,
      filePath,
      name: options.name || 'file',
      formData,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: options.timeout || 120000,
      success(res) {
        let data;
        try {
          data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        } catch {
          reject(new Error('服务器响应格式错误'));
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else if (res.statusCode === 401 && token && !retried) {
          app.clearSession();
          wx.showToast({ title: '登录已失效，请重新登录', icon: 'none' });
          setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 300);
          reject(new Error('登录已失效，请重新登录'));
        } else {
          const msg = (data && data.detail) || `上传失败 (${res.statusCode})`;
          wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        }
      },
      fail(rawError) {
        logUploadFailure(rawError);
        const error = buildUploadError(rawError);
        if (!options.silent) wx.showToast({ title: error.message, icon: 'none' });
        reject(error);
      },
    });
    if (options.onProgress && uploadTask && uploadTask.onProgressUpdate) {
      uploadTask.onProgressUpdate(options.onProgress);
    }
  });
}

/** SSE 进度轮询（小程序不支持原生 SSE，改用定时轮询）*/
function pollTask(taskId, onProgress, onDone, onError) {
  let timer = null;
  let stopped = false;
  const startedAt = Date.now();
  // 后端单次出题最长 30 分钟，前端等待上限要覆盖它，否则任务还在跑就先报超时。
  const maxWaitMs = 30 * 60 * 1000;
  let delay = 1500;

  function poll() {
    if (stopped) return;
    if (Date.now() - startedAt >= maxWaitMs) {
      stopped = true;
      onError && onError('任务等待超时，请稍后在题库列表查看');
      return;
    }
    request({ url: `/api/task/${taskId}`, silent: true }).then(data => {
      if (stopped) return;
      onProgress && onProgress(data);
      if (data.status === 'done') {
        stopped = true;
        onDone && onDone(data);
      } else if (data.status === 'failed') {
        stopped = true;
        onError && onError(data.error || '生成失败');
      } else {
        delay = 1500;
        timer = setTimeout(poll, delay);
      }
    }).catch(() => {
      if (!stopped) {
        delay = Math.min(delay * 2, 10000);
        timer = setTimeout(poll, delay);
      }
    });
  }

  poll();
  return () => { stopped = true; clearTimeout(timer); };
}

module.exports = { request, uploadFile, pollTask, getUserId };
