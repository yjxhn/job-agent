// ==UserScript==
// @name         智联招聘职位捕获器 (Zhilian Job Capture)
// @namespace    https://github.com/job-agent
// @version      1.0.0
// @description  在 sou.zhaopin.com 搜索时自动捕获 /c/i/search/positions API 响应，转发到本地 agent 入库
// @author       job-agent
// @match        https://sou.zhaopin.com/*
// @match        https://fe-api.zhaopin.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @run-at       document-start
// ==/UserScript==

(function () {
  'use strict';

  const CAPTURE_URL = 'http://127.0.0.1:8778/zhilian/capture';
  const API_PATTERN = /\/c\/i\/search\/positions/;
  let capturedCount = 0;
  let badgeEl = null;

  // ---- Status badge (bottom-right corner) ----
  function ensureBadge() {
    if (badgeEl && document.body.contains(badgeEl)) return;
    badgeEl = document.createElement('div');
    badgeEl.id = 'zhilian-capture-badge';
    badgeEl.style.cssText =
      'position:fixed;bottom:16px;right:16px;z-index:99999;' +
      'background:#1a1a2e;color:#e2e8f0;padding:8px 14px;' +
      'border-radius:8px;font-size:13px;font-family:system-ui,sans-serif;' +
      'box-shadow:0 4px 12px rgba(0,0,0,.25);pointer-events:none;' +
      'transition:opacity .3s;opacity:0.92';
    badgeEl.textContent = '已捕获 0 条到 agent';
    document.body.appendChild(badgeEl);
  }

  function updateBadge(count) {
    capturedCount += count;
    if (!badgeEl) ensureBadge();
    badgeEl.textContent =
      '已捕获 ' + capturedCount + ' 条到 agent';
    badgeEl.style.opacity = '0.92';
    setTimeout(function () {
      if (badgeEl) badgeEl.style.opacity = '0.75';
    }, 3000);
  }

  // ---- Send jobs to local agent server via GM_xmlhttpRequest ----
  function forwardJobs(jobs, keyword, page) {
    if (!jobs || jobs.length === 0) return;
    var payload = JSON.stringify({
      jobs: jobs,
      kw: keyword || '',
      page: page || 1,
      captured_at: new Date().toISOString(),
    });
    GM_xmlhttpRequest({
      method: 'POST',
      url: CAPTURE_URL,
      headers: { 'Content-Type': 'application/json' },
      data: payload,
      timeout: 8000,
      onload: function (resp) {
        if (resp.status === 200) {
          try {
            var result = JSON.parse(resp.responseText);
            console.log(
              '[ZhilianCapture] POST OK: ingested=' +
                result.ingested +
                ' deduped=' +
                result.deduped +
                ' total=' +
                result.total
            );
            updateBadge(result.ingested);
          } catch (_) {
            console.log('[ZhilianCapture] POST OK (no JSON body)');
          }
        } else {
          console.warn(
            '[ZhilianCapture] POST failed: HTTP ' +
              resp.status +
              ' — agent server running?'
          );
        }
      },
      onerror: function () {
        console.warn(
          '[ZhilianCapture] POST network error — agent server running on :8778?'
        );
      },
    });
  }

  // ---- Extract jobs from API response body ----
  function extractJobs(body) {
    try {
      if (typeof body === 'string') {
        body = JSON.parse(body);
      }
      var data = body && body.data;
      if (!data) return null;
      var list = data.list;
      var count = data.count;
      // Attempt to read keyword from request context (injected below)
      var kw = body._capture_kw || '';
      var page = (body._capture_page > 0 ? body._capture_page : 1) || 1;
      if (Array.isArray(list) && list.length > 0) {
        return { jobs: list, kw: kw, page: page };
      }
      console.log(
        '[ZhilianCapture] API response: count=' +
          count +
          ' list_len=' +
          (list ? list.length : 0) +
          ' — nothing to forward'
      );
      return null;
    } catch (_) {
      return null;
    }
  }

  // ---- Hook window.fetch ----
  var nativeFetch = window.fetch;
  window.fetch = function (url, options) {
    var urlStr = typeof url === 'string' ? url : url && url.url ? url.url : url && url.href ? url.href : '';

    // Track request body to infer keyword/page for the response
    var kw = '';
    var page = 1;
    if (options && options.body) {
      try {
        var reqBody = JSON.parse(options.body);
        kw = reqBody.S_SOU_FULL_INDEX || '';
        page = reqBody.pageIndex || 1;
      } catch (_) {}
    }

    var promise = nativeFetch.apply(this, arguments);

    if (urlStr && API_PATTERN.test(urlStr)) {
      promise
        .then(function (resp) {
          var cloned = resp.clone();
          cloned
            .json()
            .then(function (body) {
              body._capture_kw = kw;
              body._capture_page = page;
              var result = extractJobs(body);
              if (result) {
                forwardJobs(result.jobs, result.kw, result.page);
              }
            })
            .catch(function () {});
        })
        .catch(function () {});
    }
    return promise;
  };

  // ---- Hook XMLHttpRequest ----
  var NativeXHR = window.XMLHttpRequest;
  window.XMLHttpRequest = function () {
    var xhr = new NativeXHR();
    var _open = xhr.open;
    var _send = xhr.send;
    var _url = '';
    var _kw = '';
    var _page = 1;

    xhr.open = function (method, url) {
      _url = typeof url === 'string' ? url : url && url.toString ? url.toString() : '';
      return _open.apply(this, arguments);
    };

    xhr.send = function (body) {
      // Infer keyword/page from request body
      if (body) {
        try {
          var reqBody = typeof body === 'string' ? JSON.parse(body) : body;
          _kw = reqBody.S_SOU_FULL_INDEX || '';
          _page = reqBody.pageIndex || 1;
        } catch (_) {}
      }

      // Hook load event
      xhr.addEventListener('load', function () {
        if (!_url || !API_PATTERN.test(_url)) return;
        try {
          var respBody =
            typeof xhr.responseText === 'string'
              ? JSON.parse(xhr.responseText)
              : xhr.response;
          respBody._capture_kw = _kw;
          respBody._capture_page = _page;
          var result = extractJobs(respBody);
          if (result) {
            forwardJobs(result.jobs, result.kw, result.page);
          }
        } catch (_) {}
      });

      return _send.apply(this, arguments);
    };

    return xhr;
  };

  // ---- Init ----
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureBadge);
  } else {
    ensureBadge();
  }
  console.log('[ZhilianCapture] Initialized — monitoring fe-api.zhaopin.com/c/i/search/positions');
})();
