// ==UserScript==
// @name         mmpfp
// @description  Make more power for problems
// @version      0.0.1
// @author       marscheng
// @match        *://www.luogu.com.cn/record/list*
// @match        *://www.luogu.com/record/list*
// @connect      localhost
// @grant        GM_xmlhttpRequest
// @run-at       document-idle
// ==/UserScript==

(function () {
    console.log("start mmpfp");
    setTimeout(() => {
        console.log("load mmpfp");
        const host = "http://localhost:8000";
        if (/www\.luogu\.com(\.cn)?$/.test(location.hostname)) {
            function handle_time(str) {
                // 按空格拆分为日期部分和时间部分
                const parts = str.trim().split(' ');
                if (parts.length !== 2) {
                    throw new Error('Invalid format: expected "YYYY-MM-DD HH:mm" or "MM-DD HH:mm:ss"');
                }

                const datePart = parts[0];
                const timePart = parts[1];

                // 解析日期
                const dateSegments = datePart.split('-');
                let year, month, day;
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
            const input_group = document.getElementsByClassName("input-group")[0];
            const read_btn = document.createElement("div");
            read_btn.innerHTML = '<button type="button" class="lfe-form-sz-small">读取记录</button>';
            input_group.appendChild(read_btn);

            function push_record() {
                const record_list = document.getElementsByClassName("row-wrap")[0];
                let record = [];

                for (const rec of record_list.getElementsByClassName("row")) {
                    const href = rec.getElementsByClassName("status")[0].getElementsByTagName("a")[0].getAttribute("href");
                    const pid = rec.getElementsByClassName("pid")[0].innerText;
                    if (!pid.startsWith("P"))
                        continue;
                    record.push({
                        time: handle_time(rec.getElementsByClassName("lfe-caption")[0].innerText),
                        status: (rec.getElementsByClassName("status-name")[0].innerText == "Accepted"),
                        pid,
                        rid: "Luogu" + href.split("/")[2]
                    });
                    console.log("status", rec.getElementsByClassName("status-name")[0].innerText);
                }
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
    }, 3000);
})();