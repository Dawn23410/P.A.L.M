/* flag-polyfill.js — 国旗 emoji 兜底渲染
 * 问题：Windows / Segoe UI Emoji 不提供国旗字形，地区指示符对(🇨🇳)与
 *       标签序列旗帜(🏴󠁧󠁢󠁥󠁮󠁧󠁿 英格兰/苏格兰/威尔士)会回退成两个字母。
 * 解决：扫描气泡内文本节点，将国旗序列替换为本地 Twemoji SVG(<img>)，
 *       离线(file://)与在线均可用；图片 404 时自动回退为原字符(仍显示字母)。
 * 注意：仅处理 pre/code/script/style 之外的文本，且不改动生产渲染逻辑，
 *       由调用方(渲染后)触发 window.FlagPolyfill.process(bubble)。
 */
window.FlagPolyfill = (function () {
  "use strict";

  // 相对路径：file:// 双击与 http 服务均可用（与 lang/emoji 垫片同源策略一致）
  var FLAG_DIR = "vendor/flags/";

  // 地区指示符国旗：两个地区指示符码点 (U+1F1E6..U+1F1FF)
  var RE_REGION = /\uD83C[\uDDE6-\uDDFF]\uD83C[\uDDE6-\uDDFF]/g;
  // 标签序列国旗：🏴 + 若干标签字符 + 取消标签(U+E007F)
  var RE_SUBDIV = /\uD83C\uDFF4(?:\uDB40[\uDC61-\uDC7A])+\uDB40\uDC7F/g;
  var RE = new RegExp(RE_REGION.source + "|" + RE_SUBDIV.source, "g");

  // 将国旗码点序列转为 Twemoji 文件名（小写十六进制，'-' 连接）
  function cpName(seq) {
    var parts = [];
    for (var i = 0; i < seq.length; i++) {
      var c = seq.codePointAt(i);
      parts.push(c.toString(16).toLowerCase());
      if (c > 0xffff) i++; // 消耗代理对低 surrogate
    }
    return parts.join("-") + ".svg";
  }

  function inSkippedParent(node, root) {
    var p = node.parentNode;
    while (p && p !== root) {
      var t = (p.tagName || "").toLowerCase();
      if (t === "pre" || t === "code" || t === "script" || t === "style") return true;
      p = p.parentNode;
    }
    return false;
  }

  function process(root) {
    if (!root || !root.ownerDocument) return;
    var doc = root.ownerDocument;

    // 收集需处理的文本节点（跳过代码块与脚本样式）
    var textNodes = [];
    var walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, function (node) {
      if (!node.nodeValue || node.nodeValue.indexOf("\uD83C") < 0) return NodeFilter.FILTER_REJECT;
      if (inSkippedParent(node, root)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    });
    var n;
    while ((n = walker.nextNode())) textNodes.push(n);

    textNodes.forEach(function (textNode) {
      var txt = textNode.nodeValue;
      var frag = doc.createDocumentFragment();
      var last = 0, m;
      RE.lastIndex = 0;
      while ((m = RE.exec(txt)) !== null) {
        var matched = m[0];
        if (m.index > last) frag.appendChild(doc.createTextNode(txt.slice(last, m.index)));
        var img = doc.createElement("img");
        img.className = "emoji-flag";
        img.alt = matched;
        img.setAttribute("aria-label", matched);
        img.setAttribute("draggable", "false");
        img.src = FLAG_DIR + cpName(matched);
        img.addEventListener("error", function () {
          if (img.parentNode) {
            img.parentNode.replaceChild(doc.createTextNode(img.alt), img);
          }
        });
        frag.appendChild(img);
        last = m.index + matched.length;
      }
      if (last > 0) {
        if (last < txt.length) frag.appendChild(doc.createTextNode(txt.slice(last)));
        textNode.parentNode.replaceChild(frag, textNode);
      }
    });
  }

  return { process: process, cpName: cpName };
})();
