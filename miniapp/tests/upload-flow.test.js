'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadRequestModule(uploadFailure) {
  const toasts = [];
  const errors = [];
  const app = {
    globalData: {
      accessToken: 'test-token',
      baseUrl: 'https://api.quizapp.chat',
    },
    ensureLogin: async () => ({ id: 1 }),
  };
  const wx = {
    showToast: options => toasts.push(options.title),
    uploadFile(options) {
      queueMicrotask(() => options.fail(uploadFailure));
      return { onProgressUpdate() {} };
    },
  };
  const module = { exports: {} };
  const source = fs.readFileSync(path.join(__dirname, '..', 'utils', 'request.js'), 'utf8');
  vm.runInNewContext(source, {
    module,
    exports: module.exports,
    require,
    getApp: () => app,
    wx,
    Promise,
    Error,
    setTimeout,
    clearTimeout,
    console: { error: (...args) => errors.push(args) },
  });
  return { requestModule: module.exports, toasts, errors };
}

function loadUploadPage(wx) {
  let page;
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'pages', 'upload', 'upload.js'),
    'utf8',
  );
  vm.runInNewContext(source, {
    Page: definition => { page = definition; },
    require: () => ({ uploadFile: async () => ({}), request: async () => ({}) }),
    wx,
    Promise,
    Error,
    Number,
    Math,
    encodeURIComponent,
  });
  page.data = JSON.parse(JSON.stringify(page.data));
  page.setData = update => Object.assign(page.data, update);
  return page;
}

async function testUploadPreservesWechatFailureDetails() {
  const fixture = loadRequestModule({
    errMsg: 'uploadFile:fail net::ERR_CONNECTION_RESET',
    errno: 8,
  });

  await assert.rejects(
    fixture.requestModule.uploadFile('wxfile://tmp/document.docx'),
    error => {
      assert.match(error.message, /服务器连接被中止/);
      assert.equal(error.errMsg, 'uploadFile:fail net::ERR_CONNECTION_RESET');
      assert.equal(error.errno, 8);
      return true;
    },
  );
  assert.deepEqual(fixture.toasts, ['服务器连接被中止，请稍后重试']);
  assert.equal(fixture.errors.length, 1);
  assert.equal(fixture.errors[0][1].errno, 8);
}

async function testUploadReportsExpiredTemporaryFile() {
  const fixture = loadRequestModule({
    errMsg: 'uploadFile:fail no such file wxfile://tmp/missing.docx',
    errno: 1300002,
  });

  await assert.rejects(
    fixture.requestModule.uploadFile('wxfile://tmp/missing.docx'),
    /所选文件已失效/,
  );
  assert.deepEqual(fixture.toasts, ['所选文件已失效，请重新选择']);
  assert.equal(fixture.errors[0][1].errMsg.includes('missing.docx'), false);
}

async function testUploadReportsMissingWechatDomain() {
  const fixture = loadRequestModule({
    errMsg: 'uploadFile:fail url not in domain list',
    errno: 600001,
  });

  await assert.rejects(
    fixture.requestModule.uploadFile('wxfile://tmp/document.docx'),
    /uploadFile 合法域名/,
  );
}

function testEmptyFileCannotBeSelected() {
  const toasts = [];
  const page = loadUploadPage({
    chooseMessageFile(options) {
      options.success({
        tempFiles: [{ path: 'wxfile://tmp/empty.docx', name: 'empty.docx', size: 0 }],
      });
    },
    showToast: options => toasts.push(options.title),
  });

  page.chooseFile();
  assert.equal(page.data.selectedFile, null);
  assert.deepEqual(toasts, ['文件为空，请重新选择']);
}

function testSmallFileUsesKbInsteadOfZeroMb() {
  const page = loadUploadPage({});
  assert.equal(page._formatFileSize(40 * 1024), '40 KB');
}

async function testExpiredFileIsRejectedBeforeUpload() {
  const page = loadUploadPage({
    getFileSystemManager: () => ({
      stat: options => options.fail({ errMsg: 'stat:fail no such file' }),
    }),
  });

  await assert.rejects(
    page._validateSelectedFile({ path: 'wxfile://tmp/missing.docx', sizeBytes: 1024 }),
    /所选文件已失效/,
  );
}

(async () => {
  await testUploadPreservesWechatFailureDetails();
  await testUploadReportsExpiredTemporaryFile();
  await testUploadReportsMissingWechatDomain();
  testEmptyFileCannotBeSelected();
  testSmallFileUsesKbInsteadOfZeroMb();
  await testExpiredFileIsRejectedBeforeUpload();
  console.log('miniapp upload flow tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
