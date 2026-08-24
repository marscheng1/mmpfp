// ==UserScript==
// @name         mmpfp
// @description  Make more power for problems
// @version      0.0.1
// @author       marscheng
// @match        *://www.luogu.com.cn/record/list*
// @match        *://www.luogu.com/record/list*
// @match        *://www.luogu.com.cn/record/*
// @match        *://www.luogu.com/record/*
// @match        *://qoj.ac/submissions*
// @match        *://qoj.ac/submission/*
// @match        *://codeforces.com/submissions/*
// @match        *://codeforces.com/problemset/status*
// @match        *://codeforces.com/contest/*/status*
// @match        *://codeforces.com/contest/*/my
// @match        *://acm.hdu.edu.cn/contest/status?*
// @match        *://atcoder.jp/contests/*/submissions*
// @connect      localhost
// @grant        GM_xmlhttpRequest
// @run-at       document-idle
// ==/UserScript==

const host = "http://localhost:8000";
const debug = true;

function handle_time(str) {
    // 按空格拆分为日期部分和时间部分
    const parts = str.trim().split(' ');
    if (parts.length < 2) {
        throw new Error('Invalid format: expected "YYYY-MM-DD HH:mm" or "MM-DD HH:mm:ss"');
    }

    const datePart = parts[0];
    const timePart = parts[1];

    // 解析日期
    let year, month, day;

    // 处理 Codeforces 格式: "Jul/17/2025"
    if (datePart.includes('/')) {
        const segs = datePart.split('/');
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        month = monthNames.indexOf(segs[0]);
        day = parseInt(segs[1], 10);
        year = parseInt(segs[2], 10);
    } else {
        const dateSegments = datePart.split('-');
        if (dateSegments.length === 3) {
            // 判断是否包含年份：第一个字段长度为4则为年份
            if (dateSegments[0].length === 4) {
                year = parseInt(dateSegments[0], 10);
                month = parseInt(dateSegments[1], 10) - 1; // JS 月份从0开始
                day = parseInt(dateSegments[2], 10);
            } else {
                throw new Error('Unsupported date format');
            }
        } else if (dateSegments.length === 2) {
            // 无年份，月-日
            const currentYear = new Date().getFullYear();
            year = currentYear;
            month = parseInt(dateSegments[0], 10) - 1;
            day = parseInt(dateSegments[1], 10);
        } else {
            throw new Error('Invalid date part');
        }
    }

    // 解析时间
    const timeSegments = timePart.split(':');
    let hours, minutes, seconds = 0;
    if (timeSegments.length === 2) {
        hours = parseInt(timeSegments[0], 10);
        minutes = parseInt(timeSegments[1], 10);
    } else if (timeSegments.length === 3) {
        hours = parseInt(timeSegments[0], 10);
        minutes = parseInt(timeSegments[1], 10);
        seconds = parseInt(timeSegments[2], 10);
    } else {
        throw new Error('Invalid time part');
    }

    // 创建 Date 对象（本地时间）
    const dateObj = new Date(year, month, day, hours, minutes, seconds);
    // 检查是否有效
    if (isNaN(dateObj.getTime())) {
        throw new Error('Invalid date/time');
    }

    // 返回 Unix 时间戳（秒）
    return Math.floor(dateObj.getTime() / 1000);
}
function push_record_to_server(record) {
    console.log("push record", record);
    if (debug) return;
    GM_xmlhttpRequest({
        method: "POST",
        url: `${host}/api/push_record`,
        headers: {
            'Content-Type': 'application/json'
        },
        data: JSON.stringify(record),
        onload: function (response) {
            console.log('请求成功，状态码：', response.status);
            console.log('响应内容：', response.responseText);
        },
        onerror: function (error) {
            console.error('请求失败：', error);
        }
    });
}

function luogu_record_list(user) {
    console.log("start luogu_record_list");

    const input_group = document.getElementsByClassName("input-group")[0];
    const read_btn = document.createElement("div");
    read_btn.innerHTML = '<button type="button" class="lfe-form-sz-small">读取记录</button>';
    input_group.appendChild(read_btn);

    function push_record() {
        // 获取提交列表容器
        const record_list = document.getElementsByClassName("row-wrap")[0];
        let record = [];

        // 遍历每一行提交记录
        for (const rec of record_list.getElementsByClassName("row")) {
            // 跳过非当前用户的提交
            const userLink = rec.querySelector('.user a[href^="/user/"]');
            if (!userLink) continue;
            const rowUser = userLink.getAttribute("href").split("/").pop();
            if (rowUser !== user) continue;

            // 提取提交链接，获取提交号
            const statusLink = rec.getElementsByClassName("status")[0].getElementsByTagName("a")[0];
            const href = statusLink.getAttribute("href");
            const rid = "Luogu" + href.split("/")[2];

            // 提取题号，跳过非题目提交
            const pid = rec.getElementsByClassName("pid")[0].innerText;
            if (!pid.startsWith("P")) continue;

            // 提取提交时间文本
            const timeText = rec.getElementsByClassName("lfe-caption")[0].innerText;
            // 提取评测状态
            const statusText = rec.getElementsByClassName("status-name")[0].innerText;

            record.push({
                time: handle_time(timeText),
                status: (statusText === "Accepted"),
                pid,
                rid
            });
        }
        push_record_to_server(record);
    }
    push_record();
    function read_record() {
        const lst = document.getElementsByClassName("page-bar")[0].children[1].children;
        lst[lst.length - 2].click()
        setTimeout(() => {
            push_record();
            read_record();
        }, 5000);
    }
    read_btn.addEventListener("click", read_record);
}

function luogu_record_page(user) {
    console.log("start luogu_record_page");

    // 从页面获取用户 ID
    const userLink = document.querySelector('.info-row a[href^="/user/"]');
    if (!userLink) return;
    const pageUser = userLink.getAttribute("href").split("/").pop();
    if (pageUser !== user) return;

    const infoRows = document.querySelector(".info-rows");
    const rows = infoRows.querySelectorAll(":scope > div");
    // 提交时间在最后一个 info-row 中
    const timeText = rows[rows.length - 1].children[1].innerText.trim();
    // 状态在第二个 info-row（评测状态）
    const statusText = rows[1].children[1].innerText.trim();
    // 题号在第一个 info-row（所属题目）中的 .pid
    const pid = rows[0].querySelector(".pid").innerText;

    // 提交号从 URL 获取
    const rid = "Luogu" + window.location.pathname.split("/").pop();


    push_record_to_server([{
        time: handle_time(timeText),
        status: (statusText === "Accepted"),
        pid,
        rid
    }]);
}

function qoj_record_list(user) {
    console.log("start qoj_record_list");

    const rows = document.querySelectorAll(".table tbody tr");
    let record = [];

    for (const row of rows) {
        const cells = row.querySelectorAll("td");
        const commiter = cells[2].querySelector("a").innerText.trim();
        if (commiter !== user) continue;
        // 提交号: 第1个 td 中的 a 链接
        const ridHref = cells[0].querySelector("a").getAttribute("href");
        const rid = "Qoj" + ridHref.split("/").pop();
        // 题号: 第2个 td 中的 a 链接，取最后一段数字
        const pidHref = cells[1].querySelector("a").getAttribute("href");
        const pid = "Qoj" + pidHref.split("/").pop();
        // 状态: 第4个 td 中的 .uoj-score 文本
        const statusText = cells[3].querySelector(".uoj-score").innerText.trim();
        const status = statusText.includes("✓");
        // 提交时间: 第9个 td 中的 small 文本
        const timeText = cells[8].querySelector("small").innerText.trim();

        record.push({
            time: handle_time(timeText),
            status,
            pid,
            rid
        });
    }

    push_record_to_server(record);
}

function qoj_record_page(user) {
    console.log("start qoj_record_page");

    // 获取表格中的单行数据
    const row = document.querySelector(".table tbody tr");
    if (!row) return;

    const cells = row.querySelectorAll("td");
    // 验证提交者是否匹配
    const commiter = cells[2].querySelector("a").innerText.trim();
    if (commiter !== user) return;

    // 提交号: 第1个 td 中的 a 链接
    const ridHref = cells[0].querySelector("a").getAttribute("href");
    const rid = "Qoj" + ridHref.split("/").pop();
    // 题号: 第2个 td 中的 a 链接，取最后一段数字
    const pidHref = cells[1].querySelector("a").getAttribute("href");
    const pid = "Qoj" + pidHref.split("/").pop();
    // 状态: 第4个 td 中的文本（可能是 .uoj-score 或 .small）
    const statusCell = cells[3].querySelector(".uoj-score") || cells[3].querySelector(".small");
    const statusText = statusCell ? statusCell.innerText.trim() : cells[3].innerText.trim();
    const status = statusText.includes("✓");
    // 提交时间: 第9个 td 中的 small 文本
    const timeText = cells[8].querySelector("small").innerText.trim();

    push_record_to_server([{
        time: handle_time(timeText),
        status,
        pid,
        rid
    }]);
}

function cf_record_list(user) {
    console.log("start cf_record_list");

    // 获取提交列表表格中的行
    const rows = document.querySelectorAll(".status-frame-datatable tbody tr");
    let record = [];

    for (const row of rows) {
        // 跳过表头行 (th 而非 td)
        if (row.querySelector("th")) continue;

        const cells = row.querySelectorAll("td");

        // 验证提交者是否匹配（第3列）
        const commiter = cells[2].querySelector("a").innerText.trim();
        if (commiter !== user) continue;

        // 提交号（第1列）：从 a 链接中提取数字
        const ridHref = cells[0].querySelector("a").getAttribute("href");
        const rid = "Cf" + ridHref.split("/").pop();

        // 题号（第4列）：提取 "contestId/题号"
        // 有两种可能的格式：
        //   /problemset/problem/468/C   → parts: ["", "problemset", "problem", "468", "C"]
        //   /contest/2152/problem/B     → parts: ["", "contest", "2152", "problem", "B"]
        const problemHref = cells[3].querySelector("a").getAttribute("href");
        const parts = problemHref.split("/");
        let contestId, problemId;
        if (parts[1] === "problemset") {
            contestId = parts[3];
            problemId = parts[4];
        } else { // /contest/...
            contestId = parts[2];
            problemId = parts[4];
        }
        const pid = "Cf" + contestId + problemId;

        // 状态（第6列）：检查是否包含 verdict-accepted
        const statusCell = cells[5].querySelector(".verdict-accepted");
        const status = !!statusCell;

        // 提交时间（第2列）：去掉 UTC+8 后缀
        const timeText = cells[1].innerText.trim().replace(/\s*UTC[+-]\d+.*$/, "");

        record.push({
            time: handle_time(timeText),
            status,
            pid,
            rid
        });
    }

    push_record_to_server(record);
}

function hdu_record_list() {
    console.log("start hdu_record_list");

    // 在页面顶部添加"读取记录"按钮
    const container = document.querySelector(".page-card-table")?.parentElement;
    if (!container) return;
    // 检查是否已添加按钮
    if (document.getElementById("mmpfp-hdu-btn")) return;

    const btn = document.createElement("div");
    btn.id = "mmpfp-hdu-btn";
    btn.innerHTML = '<button type="button" style="margin: 8px; padding: 4px 12px; cursor: pointer;">读取记录</button>';
    container.insertBefore(btn, container.firstChild);

    btn.addEventListener("click", function () {
        const rows = document.querySelectorAll(".page-card-table tbody tr");
        let record = [];

        for (const row of rows) {
            const cells = row.querySelectorAll("td");

            // Submit Time（第2列）
            const timeText = cells[1].innerText.trim();

            // Problem ID（第3列）：a 链接中的 pid 参数值
            const pidHref = cells[2].querySelector("a").getAttribute("href");
            const params = new URLSearchParams(pidHref.split("?")[1]);
            const cid = params.get("cid");
            const pid = `Hdu_${cid}_${params.get("pid")}`;

            // Run ID（第1列）
            const rid = `Hdu_${cid}_${cells[0].innerText.trim()}`;

            // Judge Status（第7列）：检查是否包含 class "status-accepted"
            const statusCell = cells[6];
            const status = statusCell.classList.contains("status-accepted");

            record.push({
                time: handle_time(timeText),
                status,
                pid,
                rid
            });
        }

        push_record_to_server(record);
    });
}

function atcoder_record_list(user) {
    console.log("start atcoder_record_list");

    // 获取提交列表表格中的行
    const rows = document.querySelectorAll(".table tbody tr");
    let record = [];

    for (const row of rows) {
        const cells = row.querySelectorAll("td");

        // 跳过空行
        if (!cells.length) continue;

        // 验证提交者是否匹配（用户列：User, td[2]）
        const commiter = cells[2].querySelector("a").innerText.trim();
        if (commiter !== user) continue;

        // 提交时间（Submission Time, td[0]）：<time> 文本
        const timeText = cells[0].querySelector("time").innerText.trim();

        // 题号（Task, td[1]）：a 链接提取 tasks/xxx 最后一段
        const taskHref = cells[1].querySelector("a").getAttribute("href");
        const pid = "Atcoder" + taskHref.split("/tasks/").pop();

        // 状态（Status, td[6]）：检查 .label 文本是否为 "AC"
        const statusCell = cells[6].querySelector(".label");
        const statusText = statusCell ? statusCell.innerText.trim() : "";
        const status = statusText === "AC";

        // 提交号（Detail, td[9]）：Detail 链接最后一段
        const detailLink = cells[9].querySelector("a");
        const rid = "Atcoder" + detailLink.getAttribute("href").split("/").pop();

        record.push({
            time: handle_time(timeText),
            status,
            pid,
            rid
        });
    }

    push_record_to_server(record);
}

(function () {
    console.log("start mmpfp", "debug=", debug);
    setTimeout(() => {
        const url = window.location.href.split("?")[0].split("//")[1];
        const hostname = window.location.hostname;
        const group = {
            luogu: ["www.luogu.com.cn", "www.luogu.com"],
            qoj: ["qoj.ac"],
            cf: ["codeforces.com"],
            hdu: ["acm.hdu.edu.cn"],
            atcoder: ["atcoder.jp"],
        }
        console.log("load mmpfp on", hostname, url);
        if (group.luogu.includes(hostname)) {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/luogu`,
                onload: function (response) {
                    const apiUser = JSON.parse(response.responseText);
                    if (url === `${hostname}/record/list`) {
                        luogu_record_list(apiUser);
                    } else if (new RegExp(`${hostname}/record/\\d+`).test(url)) {
                        luogu_record_page(apiUser);
                    }
                }
            });
        } else if (group.qoj.includes(hostname)) {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/qoj`,
                onload: function (response) {
                    const apiUser = JSON.parse(response.responseText);
                    if (url === `${hostname}/submissions`) {
                        qoj_record_list(apiUser);
                    } else if (new RegExp(`${hostname}/submission/\\d+`).test(url)) {
                        qoj_record_page(apiUser);
                    }
                }
            });
        } else if (group.cf.includes(hostname)) {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/cf`,
                onload: function (response) {
                    const apiUser = JSON.parse(response.responseText);
                    if (url === `${hostname}/submissions/${apiUser}` ||
                        url === `${hostname}/problemset/status` ||
                        new RegExp(`${hostname}/contest/\\d+/status`).test(url) ||
                        new RegExp(`${hostname}/contest/\\d+/my`).test(url)
                    ) {
                        cf_record_list(apiUser);
                    }
                }
            });
        } else if (group.hdu.includes(hostname)) {
            if (url.includes("contest/status")) {
                hdu_record_list();
            }
        } else if (group.atcoder.includes(hostname)) {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/atcoder`,
                onload: function (response) {
                    const apiUser = JSON.parse(response.responseText);
                    if (new RegExp(`${hostname}/contests/.+/submissions.*`).test(url)) {
                        atcoder_record_list(apiUser);
                    }
                }
            });
        }
    }, 3000);
})();