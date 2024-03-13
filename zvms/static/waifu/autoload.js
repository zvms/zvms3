function loadLive2d() {
        $("<link>").attr({href: "/static/waifu/waifu.css", rel: "stylesheet", type: "text/css"}).appendTo('head');
        $('body').append('<div class="waifu" width="300" height="800"><div class="waifu-tips"></div><canvas id="live2d" class="live2d" width="300" height="800"></canvas><div class="waifu-tool"><span class="fui-home"></span> <span class="fui-chat"></span> <span class="fui-eye"></span> <span class="fui-user"></span> <span class="fui-photo"></span> <span class="fui-info-circle"></span> <span class="fui-cross"></span></div></div>');
        window.onsubmit = e => {
            if ($('#content').val().match(/model:off/)) {
                e.preventDefault();
                e.returnValue = '';
                $('div.waifu').remove();
                localStorage.removeItem('waifu/display');
            }
        };
        $.ajax({url: "/static/waifu/waifu-tips.js", dataType:"script", cache: true, success: function() {
            $.ajax({url: "/static/waifu/live2d.js", dataType:"script", cache: true, success: function() {
                /* 可直接修改部分参数 */
                live2d_settings['hitokotoAPI'] = "hitokoto.cn";  // 一言 API
                live2d_settings['modelId'] = 1;                  // 默认模型 ID
                live2d_settings['modelTexturesId'] = 1;          // 默认材质 ID
                /* 在 initModel 前添加 */
                initModel("/static/waifu/waifu-tips.json");
            }});
        }});
}
try {
    if (localStorage.getItem('waifu/display')) {
        loadLive2d();
    } else {
        window.onsubmit = e => {
            if ($('#content').val().match(/model:on/)) {
                e.preventDefault();
                e.returnValue = '';
                localStorage.setItem('waifu/display', true);
                loadLive2d();
            }
        };
    }
} catch(err) { console.log("[Error] JQuery is not defined.") }
