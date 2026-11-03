// ==UserScript==
// @name         mmpfp
// @description  Make more power for problems
// @version      0.0.10
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
// @match        *://codeforces.com/gym/*/status*
// @match        *://codeforces.com/gym/*/my*
// @match        *://acm.hdu.edu.cn/contest/status?*
// @match        *://atcoder.jp/contests/*/submissions*
// @match        *://www.mxoj.net/submission/list*
// @match        *://hfoj.net/*
// @match        *://newoj.daimayuan.top/*
// @match        *://uoj.ac/submissions*
// @match        *://loj.ac/*
// @match        *://cses.fi/problemset/result/*
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

    const rows = document.querySelectorAll(".row-wrap .row");
    const record = [];

    for (const row of rows) {
        try {
            // 列表可能展示其他用户的提交，只收集服务中配置的洛谷用户。
            const userLink = row.querySelector('.user a[href^="/user/"]');
            if (!userLink) continue;
            const rowUser = userLink.getAttribute("href").split("/").filter(Boolean).pop();
            if (rowUser !== String(user)) continue;

            const statusLink = row.querySelector('a.status[href*="/record/"]');
            const problemLink = row.querySelector('.problem a[href*="/problem/"]');
            const timeElement = row.querySelector(".user .lfe-caption");
            if (!statusLink || !problemLink || !timeElement) continue;

            const recordMatch = new URL(statusLink.href, window.location.origin)
                .pathname.match(/^\/record\/(\d+)\/?$/);
            if (!recordMatch) continue;

            const pid = new URL(problemLink.href, window.location.origin)
                .pathname.split("/").filter(Boolean).pop();
            // 与旧逻辑保持一致，只记录普通题库中的 P 类题目。
            if (!pid || !pid.startsWith("P")) continue;

            const statusText = statusLink.querySelector("span")?.textContent.trim() || "";
            record.push({
                time: handle_time(timeElement.textContent.trim()),
                status: statusText === "Accepted",
                pid,
                rid: `Luogu${recordMatch[1]}`
            });
        } catch (error) {
            console.warn("skip malformed Luogu submission row", error, row);
        }
    }

    // 新版界面仅抓取当前页，不再自动翻页读取历史记录。
    push_record_to_server(record);
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

function uoj_record_list(user) {
    console.log("start uoj_record_list");

    const expectedUser = typeof user === "string" ? user.trim() : "";
    if (!expectedUser) return;

    const rows = document.querySelectorAll(".uoj-content .table tbody tr");
    const record = [];

    for (const row of rows) {
        try {
            const cells = row.querySelectorAll("td");
            if (cells.length < 9) continue;

            const userLink = cells[2].querySelector('a.uoj-username[href*="/user/profile/"]');
            if (!userLink) continue;
            const userUrl = new URL(userLink.getAttribute("href"), window.location.href);
            const userMatch = userUrl.pathname.match(/^\/user\/profile\/([^/]+)\/?$/);
            if (!userMatch || decodeURIComponent(userMatch[1]) !== expectedUser) continue;

            const recordLink = cells[0].querySelector('a[href*="/submission/"]');
            const problemLink = cells[1].querySelector('a[href*="/problem/"]');
            const timeElement = cells[8].querySelector("small");
            if (!recordLink || !problemLink || !timeElement) continue;

            const recordUrl = new URL(recordLink.getAttribute("href"), window.location.href);
            const problemUrl = new URL(problemLink.getAttribute("href"), window.location.href);
            const recordMatch = recordUrl.pathname.match(/^\/submission\/(\d+)\/?$/);
            const problemMatch = problemUrl.pathname.match(/^\/problem\/(\d+)\/?$/);
            if (!recordMatch || !problemMatch) continue;

            // UOJ 的结果列显示数值分数，100 分才记为通过。
            const score = cells[3].querySelector(".uoj-score");
            const scoreText = score ? score.textContent.trim() : "";
            record.push({
                time: handle_time(timeElement.textContent.trim()),
                status: scoreText !== "" && Number(scoreText) === 100,
                pid: `Uoj${problemMatch[1]}`,
                rid: `Uoj${recordMatch[1]}`
            });
        } catch (error) {
            console.warn("skip malformed UOJ submission row", error, row);
        }
    }

    if (record.length) push_record_to_server(record);
}

function loj_record_list(user) {
    console.log("start loj_record_list");

    const expectedUser = typeof user === "string" ? user.trim() : "";
    if (!expectedUser) return;

    const seen = new Map();
    const pendingStatuses = new Set(["Pending", "Compiling", "Running", "Judging"]);
    function read_records() {
        if (!/^\/s\/?$/.test(window.location.pathname)) return;
        const record = [];
        // 使用稳定的表格、链接和状态文本，不依赖构建生成的 CSS 类名。
        for (const row of document.querySelectorAll("#root table.ui.table tbody tr")) {
            try {
                const cells = row.querySelectorAll("td");
                if (cells.length < 7) continue;
                const userLink = cells[2].querySelector('a[href*="/u/"]');
                const problemLink = cells[2].querySelector('a[href*="/p/"]');
                const recordLink = cells[0].querySelector('a[href*="/s/"]');
                const statusElement = cells[0].querySelector(".statustext");
                if (!userLink || !problemLink || !recordLink || !statusElement) continue;

                const userUrl = new URL(userLink.getAttribute("href"), window.location.href);
                const userMatch = userUrl.pathname.match(/^\/u\/([^/]+)\/?$/);
                if (!userMatch || decodeURIComponent(userMatch[1]) !== expectedUser) continue;
                const recordUrl = new URL(recordLink.getAttribute("href"), window.location.href);
                const problemUrl = new URL(problemLink.getAttribute("href"), window.location.href);
                const recordMatch = recordUrl.pathname.match(/^\/s\/(\d+)\/?$/);
                const problemMatch = problemUrl.pathname.match(/^\/p\/(\d+)\/?$/);
                if (!recordMatch || !problemMatch) continue;

                const statusText = statusElement.textContent.trim();
                if (!statusText || pendingStatuses.has(statusText)) continue;
                // 显示文本省略年份，title 才包含完整的提交时间。
                const timeText = cells[6].getAttribute("title");
                if (!timeText || !/^\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}:\d{2}$/.test(timeText.trim())) continue;
                const rec = {
                    time: handle_time(timeText),
                    status: statusText === "Accepted",
                    pid: `Loj${problemMatch[1]}`,
                    rid: `Loj${recordMatch[1]}`
                };
                const signature = JSON.stringify(rec);
                if (seen.get(rec.rid) === signature) continue;
                seen.set(rec.rid, signature);
                record.push(rec);
            } catch (error) {
                console.warn("skip malformed LOJ submission row", error, row);
            }
        }
        if (record.length) push_record_to_server(record);
    }

    // LOJ 是单页应用，筛选、手动翻页和评测结果变化都可能在原页面内完成。
    const root = document.getElementById("root") || document.body;
    if (root) {
        let timer;
        const observer = new MutationObserver(() => {
            clearTimeout(timer);
            timer = setTimeout(read_records, 250);
        });
        observer.observe(root, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ["href", "title"]
        });
    }
    read_records();
}

function cses_record_page(user) {
    console.log("start cses_record_page");

    const expectedUser = typeof user === "string" ? user.trim() : "";
    if (!expectedUser) return;
    const summary = document.querySelector(".content table.summary-table");
    if (!summary) return;

    let lastSignature;
    function read_record() {
        try {
            const recordMatch = window.location.pathname.match(/^\/problemset\/result\/(\d+)\/?$/);
            if (!recordMatch) return;

            const fields = new Map();
            for (const row of summary.querySelectorAll("tr")) {
                const cells = row.querySelectorAll("td");
                if (cells.length < 2) continue;
                const key = cells[0].textContent.trim().replace(/:$/, "").toLowerCase();
                fields.set(key, cells[1]);
            }

            // 顶栏账号不代表这次提交的用户，必须读取 Submission details 的 Sender。
            if (fields.get("sender")?.textContent.trim() !== expectedUser) return;
            const statusText = fields.get("status")?.textContent.trim().toUpperCase();
            const compileError = statusText === "COMPILE ERROR" || statusText === "COMPILATION ERROR";
            if (statusText !== "READY" && !compileError) return;

            const resultText = fields.get("result")?.textContent.trim().toUpperCase() || "";
            if (!compileError && (!resultText || resultText === "--")) return;
            const taskLink = fields.get("task")?.querySelector('a[href*="/problemset/task/"]');
            if (!taskLink) return;
            const taskUrl = new URL(taskLink.getAttribute("href"), window.location.href);
            const taskMatch = taskUrl.pathname.match(/^\/problemset\/task\/(\d+)\/?$/);
            if (!taskMatch) return;

            // CSES 给出明确的 UTC 偏移，不能使用浏览器的本地时区解析。
            const timeText = fields.get("submission time")?.textContent.trim() || "";
            const timeMatch = timeText.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([+-]\d{2})(\d{2})$/);
            if (!timeMatch) return;
            const time = Math.floor(Date.parse(`${timeMatch[1]}T${timeMatch[2]}${timeMatch[3]}:${timeMatch[4]}`) / 1000);
            if (!Number.isSafeInteger(time) || time < 0) return;

            const rec = {
                time,
                status: !compileError && resultText === "ACCEPTED",
                pid: `Cses${taskMatch[1]}`,
                rid: `Cses${recordMatch[1]}`
            };
            const signature = JSON.stringify(rec);
            if (signature === lastSignature) return;
            lastSignature = signature;
            push_record_to_server([rec]);
        } catch (error) {
            console.warn("skip malformed CSES submission", error);
        }
    }

    // 打开仍在评测的结果页时，等待详情中的状态和结果更新后再采集。
    const observer = new MutationObserver(read_record);
    observer.observe(summary, { childList: true, subtree: true, characterData: true });
    read_record();
}

function cf_record_list(user) {
    console.log("start cf_record_list");

    const expectedUser = typeof user === "string" ? user.trim() : "";
    if (!expectedUser) return;

    // 获取提交列表表格中的行
    const rows = document.querySelectorAll(".status-frame-datatable tbody tr");
    const record = [];

    for (const row of rows) {
        try {
            // 跳过表头行 (th 而非 td)
            if (row.querySelector("th")) continue;

            const cells = row.querySelectorAll("td");
            if (cells.length < 6) continue;

            // 验证提交者是否匹配（第3列）
            const userLink = cells[2].querySelector('a[href*="/profile/"]');
            if (!userLink || userLink.textContent.trim() !== expectedUser) continue;

            // Gym 的源码链接可能是 # 或不可见，优先使用行上稳定的提交号。
            const submissionLink = cells[0].querySelector("a");
            let submissionId = row.getAttribute("data-submission-id")
                || submissionLink?.getAttribute("submissionid");
            if (!submissionId && submissionLink) {
                const submissionUrl = new URL(submissionLink.getAttribute("href"), window.location.href);
                submissionId = submissionUrl.pathname.match(/\/submission\/(\d+)\/?$/)?.[1];
            }
            submissionId = submissionId || cells[0].textContent.trim();
            if (!/^\d+$/.test(submissionId)) continue;
            const rid = `Cf${submissionId}`;

            // 题号（第4列）：提取 "contestId/题号"
            const problemLink = cells[3].querySelector("a");
            if (!problemLink) continue;
            const problemUrl = new URL(problemLink.getAttribute("href"), window.location.href);
            const problemMatch = problemUrl.pathname.match(/^\/problemset\/problem\/(\d+)\/([A-Za-z0-9]+)\/?$/)
                || problemUrl.pathname.match(/^\/(?:contest|gym)\/(\d+)\/problem\/([A-Za-z0-9]+)\/?$/);
            if (!problemMatch) continue;
            const pid = `Cf${problemMatch[1]}${problemMatch[2]}`;

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
        } catch (error) {
            console.warn("skip malformed Codeforces submission row", error, row);
        }
    }

    if (record.length) push_record_to_server(record);
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

function hydro_record_list({ name, prefix, buttonId, containerSelector, acceptedClass, buttonClass = "button", userId = null, autoUpload = false }) {
    console.log(`start ${name} record list`);

    const expectedUser = userId == null ? null : String(userId).trim();
    if (autoUpload && (!expectedUser || !/^\d+$/.test(expectedUser))) {
        console.warn(`${name} user ID is not configured or invalid`);
        return;
    }

    const table = document.querySelector("table.record_main__table tbody")?.closest("table");
    if (!table) return;

    function read_records() {
        const rows = document.querySelectorAll("table.record_main__table tbody tr");
        const record = [];

        for (const row of rows) {
            try {
                if (expectedUser !== null) {
                    const userLink = row.querySelector(".col--submit-by a.user-profile-name[href]");
                    if (!userLink) continue;
                    const userUrl = new URL(userLink.getAttribute("href"), window.location.href);
                    const userMatch = userUrl.pathname.match(/\/user\/(\d+)\/?$/);
                    if (!userMatch || userMatch[1] !== expectedUser) continue;
                }

                const statusLink = row.querySelector(".col--status a.record-status--text");
                const problemLink = row.querySelector('.col--problem a[href*="/p/"]');
                const timeElement = row.querySelector(".col--submit-at .time");
                if (!statusLink || !problemLink || !timeElement) continue;

                const recordUrl = new URL(statusLink.getAttribute("href"), window.location.href);
                const recordMatch = recordUrl.pathname.match(/\/record\/([^/]+)\/?$/);
                const problemUrl = new URL(problemLink.getAttribute("href"), window.location.href);
                const problemMatch = problemUrl.pathname.match(/^(.*?)\/p\/([^/]+)\/?$/);
                if (!recordMatch || !problemMatch) continue;

                // 相对时间会随页面加载变化，优先使用精确的 Unix 秒。
                const timestamp = timeElement.getAttribute("data-timestamp");
                const datetime = timeElement.getAttribute("datetime");
                let time;
                if (timestamp && /^\d+$/.test(timestamp)) {
                    time = Number(timestamp);
                } else if (datetime && /^\d+$/.test(datetime)) {
                    time = Math.floor(Number(datetime) / 1000);
                } else {
                    const timeText = timeElement.getAttribute("data-tooltip");
                    if (!timeText) continue;
                    time = handle_time(timeText);
                }
                if (!Number.isSafeInteger(time) || time <= 0) continue;

                // 保留题库路径，防止不同域中的同名题号相互合并。
                const scope = problemMatch[1].split("/").filter(Boolean).join("_");
                record.push({
                    time,
                    status: statusLink.classList.contains(acceptedClass),
                    pid: scope ? `${prefix}_${scope}_${problemMatch[2]}` : `${prefix}${problemMatch[2]}`,
                    rid: `${prefix}${recordMatch[1]}`
                });
            } catch (error) {
                console.warn(`skip malformed ${name} submission row`, error, row);
            }
        }

        if (record.length || !autoUpload) push_record_to_server(record);
    }

    if (autoUpload) {
        read_records();
        return;
    }

    if (document.getElementById(buttonId)) return;
    const container = table.closest(containerSelector) || table.parentElement;
    const btn = document.createElement("button");
    btn.id = buttonId;
    btn.type = "button";
    btn.className = buttonClass;
    btn.textContent = "读取记录";
    btn.style.cssText = "margin: 8px; padding: 4px 12px; cursor: pointer;";
    container.insertBefore(btn, container.firstChild);
    btn.addEventListener("click", read_records);
}

function hfoj_record_list() {
    hydro_record_list({
        name: "HFOJ",
        prefix: "Hfoj",
        buttonId: "mmpfp-hfoj-btn",
        containerSelector: ".section",
        acceptedClass: "pass"
    });
}

function dmy_record_list(user) {
    hydro_record_list({
        name: "Daimayuan",
        prefix: "Dmy",
        acceptedClass: "st-pass",
        userId: user,
        autoUpload: true
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
        // CE 时会变成第 td[7]
        const detailLink = cells[statusText === "CE" ? 7 : 9].querySelector("a");
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

function mxoj_record_list() {
    console.log("start mxoj_record_list");

    const rows = document.querySelectorAll(".answer-list table.table tbody tr");
    const record = [];

    for (const row of rows) {
        try {
            const cells = row.querySelectorAll("td");
            if (cells.length < 6) continue;

            // 提交号位于分值列链接的 answerId 查询参数中。
            const detailLink = cells[1].querySelector('a[href*="/submission/detail"]');
            if (!detailLink) continue;
            const detailUrl = new URL(detailLink.getAttribute("href"), window.location.origin);
            const answerId = detailUrl.searchParams.get("answerId");
            if (!answerId || !/^\d+$/.test(answerId)) continue;

            // 优先从题目链接取题号；链接缺失时回退到第一列文本。
            const problemLink = cells[2].querySelector('a.problem-title[href*="/problem/"]');
            const problemPath = problemLink
                ? new URL(problemLink.getAttribute("href"), window.location.origin).pathname
                : "";
            const rawPid = (problemPath.split("/").filter(Boolean).pop()
                || cells[0].innerText.trim()).trim();
            if (!rawPid) continue;

            // “未通过”包含“通过”文字，必须按 class 判断，不能用字符串包含关系。
            const status = !!cells[1].querySelector(".accepted");
            const timeText = cells[4].innerText.trim();

            record.push({
                time: handle_time(timeText),
                status,
                pid: `Mxoj${rawPid}`,
                rid: `Mxoj${answerId}`
            });
        } catch (error) {
            console.warn("skip malformed MXOJ submission row", error, row);
        }
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
            mxoj: ["www.mxoj.net"],
            hfoj: ["hfoj.net"],
            dmy: ["newoj.daimayuan.top"],
            uoj: ["uoj.ac"],
            loj: ["loj.ac"],
            cses: ["cses.fi"],
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
        } else if (group.uoj.includes(hostname)) {
            if (/^\/submissions\/?$/.test(window.location.pathname)) {
                GM_xmlhttpRequest({
                    method: "GET",
                    url: `${host}/api/id/uoj`,
                    onload: function (response) {
                        if (response.status !== 200) {
                            console.error("failed to load UOJ user ID", response.status);
                            return;
                        }
                        try {
                            uoj_record_list(JSON.parse(response.responseText));
                        } catch (error) {
                            console.error("invalid UOJ user ID response", error);
                        }
                    },
                    onerror: function (error) {
                        console.error("failed to load UOJ user ID", error);
                    }
                });
            }
        } else if (group.loj.includes(hostname)) {
            // 即使最初从其他页面进入，也要支持站内导航到 /s。
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/loj`,
                onload: function (response) {
                    if (response.status !== 200) {
                        console.error("failed to load LOJ user ID", response.status);
                        return;
                    }
                    try {
                        loj_record_list(JSON.parse(response.responseText));
                    } catch (error) {
                        console.error("invalid LOJ user ID response", error);
                    }
                },
                onerror: function (error) {
                    console.error("failed to load LOJ user ID", error);
                }
            });
        } else if (group.cses.includes(hostname)) {
            if (/^\/problemset\/result\/\d+\/?$/.test(window.location.pathname)) {
                GM_xmlhttpRequest({
                    method: "GET",
                    url: `${host}/api/id/cses`,
                    onload: function (response) {
                        if (response.status !== 200) {
                            console.error("failed to load CSES user ID", response.status);
                            return;
                        }
                        try {
                            cses_record_page(JSON.parse(response.responseText));
                        } catch (error) {
                            console.error("invalid CSES user ID response", error);
                        }
                    },
                    onerror: function (error) {
                        console.error("failed to load CSES user ID", error);
                    }
                });
            }
        } else if (group.cf.includes(hostname)) {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${host}/api/id/cf`,
                onload: function (response) {
                    const apiUser = JSON.parse(response.responseText);
                    const pathname = window.location.pathname.replace(/\/+$/, "");
                    if (pathname === `/submissions/${apiUser}` ||
                        pathname === "/problemset/status" ||
                        /^\/(?:contest|gym)\/\d+\/(?:status|my)$/.test(pathname)
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
        } else if (group.mxoj.includes(hostname)) {
            if (window.location.pathname.replace(/\/+$/, "") === "/submission/list") {
                mxoj_record_list();
            }
        } else if (group.hfoj.includes(hostname)) {
            if (/\/record\/?$/.test(window.location.pathname)) {
                hfoj_record_list();
            }
        } else if (group.dmy.includes(hostname)) {
            if (/\/record\/?$/.test(window.location.pathname)) {
                GM_xmlhttpRequest({
                    method: "GET",
                    url: `${host}/api/id/dmy`,
                    onload: function (response) {
                        if (response.status !== 200) {
                            console.error("failed to load Daimayuan user ID", response.status);
                            return;
                        }
                        try {
                            dmy_record_list(JSON.parse(response.responseText));
                        } catch (error) {
                            console.error("invalid Daimayuan user ID response", error);
                        }
                    },
                    onerror: function (error) {
                        console.error("failed to load Daimayuan user ID", error);
                    }
                });
            }
        }
    }, 3000);
})();
