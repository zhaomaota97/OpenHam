using System;
using System.IO;
using System.Diagnostics;
using System.Windows.Forms;
using System.Drawing;
using System.Threading;
using System.Text;

class Launcher
{
    [STAThread]
    static void Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string python  = Path.Combine(baseDir, "runtime", "python.exe");
        string marker  = Path.Combine(baseDir, "runtime", ".deps_ok");
        string mainPy  = Path.Combine(baseDir, "main.py");

        // ── 非首次：零 UI 开销，直接静默启动 ──────────────────────────
        if (File.Exists(marker))
        {
            LaunchHidden(python, mainPy, baseDir);
            return;
        }

        // ── 首次安装 ───────────────────────────────────────────────────
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        if (!File.Exists(python))
        {
            MessageBox.Show(
                "未找到 runtime\\python.exe，请确保 runtime 目录完整。",
                "OpenHam", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        var form = new InstallForm(baseDir, python);
        Application.Run(form);
        if (!form.Success) return;

        try { File.WriteAllText(marker, DateTime.Now.ToString()); } catch { }
        LaunchHidden(python, mainPy, baseDir);
    }

    // 与原 VBS "cmd /c ...", vbhide 完全等效
    static void LaunchHidden(string python, string mainPy, string baseDir)
    {
        try
        {
            string args = "/c \"\"" + python + "\" \"" + mainPy + "\"\"";
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName         = "cmd.exe";
            psi.Arguments        = args;
            psi.WorkingDirectory = baseDir;
            psi.UseShellExecute  = false;
            psi.CreateNoWindow   = true;
            psi.WindowStyle      = ProcessWindowStyle.Hidden;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("启动失败：" + ex.Message, "OpenHam",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

// ── 安装界面 ──────────────────────────────────────────────────────────
class InstallForm : Form
{
    readonly string _base, _python;
    public bool Success;

    Label      _step1Lbl, _step2Lbl;
    Label      _statusLabel;
    ProgressBar _pbStep1, _pbStep2;
    RichTextBox _log;
    Panel      _donePanel;

    // 模拟进度的计时器（UI 线程）
    System.Windows.Forms.Timer _ticker;
    int _tickTarget = 0;   // 当前活跃进度条的目标值（0-100）
    ProgressBar _activePb; // 当前被动画驱动的进度条

    public InstallForm(string baseDir, string python)
    {
        _base   = baseDir;
        _python = python;
        BuildUI();
        Load += OnLoad;
    }

    // ── UI 构建 ─────────────────────────────────────────────────────
    void BuildUI()
    {
        Text            = "OpenHam - 首次启动初始化";
        ClientSize      = new Size(580, 520);
        StartPosition   = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox     = false;
        MinimizeBox     = false;
        BackColor       = Color.FromArgb(28, 26, 20);

        // 从 exe 自身提取嵌入图标，同时正确设置任务栏和窗口图标
        try
        {
            Icon exeIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (exeIcon != null) this.Icon = exeIcon;
        }
        catch { }

        int y = 0;

        // ── 深色头部横条 ─────────────────────────────────────────────
        Panel header = new Panel();
        header.Location  = new Point(0, 0);
        header.Size      = new Size(580, 80);
        header.BackColor = Color.FromArgb(20, 18, 12);
        Controls.Add(header);

        Label appName = new Label();
        appName.Text      = "OpenHam";
        appName.ForeColor = Color.FromArgb(192, 144, 48);
        appName.Font      = new Font("Microsoft YaHei UI", 16, FontStyle.Bold);
        appName.Location  = new Point(22, 12);
        appName.Size      = new Size(300, 36);
        appName.BackColor = Color.Transparent;
        header.Controls.Add(appName);

        Label subtitle = new Label();
        subtitle.Text      = "首次启动 · 正在安装运行环境";
        subtitle.ForeColor = Color.FromArgb(100, 90, 64);
        subtitle.Font      = new Font("Microsoft YaHei UI", 9);
        subtitle.Location  = new Point(24, 50);
        subtitle.Size      = new Size(400, 20);
        subtitle.BackColor = Color.Transparent;
        header.Controls.Add(subtitle);

        y = 88;

        // ── 步骤 1 ───────────────────────────────────────────────────
        _step1Lbl = MakeLabel("① 安装 pip", 22, y, 536,
            new Font("Microsoft YaHei UI", 10, FontStyle.Bold),
            Color.FromArgb(160, 148, 110));
        Controls.Add(_step1Lbl);
        y += 26;

        _pbStep1 = MakeProgressBar(22, y, 536);
        Controls.Add(_pbStep1);
        y += 22;

        // ── 步骤 2 ───────────────────────────────────────────────────
        _step2Lbl = MakeLabel("② 安装项目依赖", 22, y + 10, 536,
            new Font("Microsoft YaHei UI", 10, FontStyle.Bold),
            Color.FromArgb(80, 72, 52));   // 灰色，未开始
        Controls.Add(_step2Lbl);
        y += 36;

        _pbStep2 = MakeProgressBar(22, y, 536);
        Controls.Add(_pbStep2);
        y += 22;

        // ── 状态行 ──────────────────────────────────────────────────
        _statusLabel = MakeLabel("请稍候，保持网络连接…", 22, y + 6, 536,
            new Font("Microsoft YaHei UI", 8.5f),
            Color.FromArgb(100, 92, 66));
        Controls.Add(_statusLabel);
        y += 30;

        // ── 日志区 ──────────────────────────────────────────────────
        _log = new RichTextBox();
        _log.ReadOnly    = true;
        _log.Location    = new Point(22, y);
        _log.Size        = new Size(536, ClientSize.Height - y - 16);
        _log.BackColor   = Color.FromArgb(16, 14, 10);
        _log.ForeColor   = Color.FromArgb(130, 122, 96);
        _log.Font        = new Font("Consolas", 8.5f);
        _log.BorderStyle = BorderStyle.None;
        _log.ScrollBars  = RichTextBoxScrollBars.Vertical;
        Controls.Add(_log);

        // ── 完成叠加层（默认隐藏） ────────────────────────────────────
        _donePanel = new Panel();
        _donePanel.Location  = _log.Location;
        _donePanel.Size      = _log.Size;
        _donePanel.BackColor = Color.FromArgb(16, 14, 10);
        _donePanel.Visible   = false;
        Controls.Add(_donePanel);

        Label doneIcon = new Label();
        doneIcon.Text      = "✅";
        doneIcon.Font      = new Font("Segoe UI Emoji", 30);
        doneIcon.ForeColor = Color.FromArgb(100, 200, 120);
        doneIcon.Location  = new Point(0, 30);
        doneIcon.Size      = new Size(536, 56);
        doneIcon.TextAlign = ContentAlignment.MiddleCenter;
        doneIcon.BackColor = Color.Transparent;
        _donePanel.Controls.Add(doneIcon);

        Label doneTitle = new Label();
        doneTitle.Text      = "安装成功！";
        doneTitle.ForeColor = Color.FromArgb(192, 144, 48);
        doneTitle.Font      = new Font("Microsoft YaHei UI", 15, FontStyle.Bold);
        doneTitle.Location  = new Point(0, 96);
        doneTitle.Size      = new Size(536, 36);
        doneTitle.TextAlign = ContentAlignment.MiddleCenter;
        doneTitle.BackColor = Color.Transparent;
        _donePanel.Controls.Add(doneTitle);

        // 提示框
        Panel tipBox = new Panel();
        tipBox.Location  = new Point(68, 146);
        tipBox.Size      = new Size(400, 64);
        tipBox.BackColor = Color.FromArgb(22, 20, 14);
        _donePanel.Controls.Add(tipBox);

        Label tipKey = new Label();
        tipKey.Text      = "💡  Alt + 空格   呼出 / 隐藏输入框";
        tipKey.ForeColor = Color.FromArgb(180, 165, 120);
        tipKey.Font      = new Font("Microsoft YaHei UI", 10, FontStyle.Bold);
        tipKey.Location  = new Point(16, 10);
        tipKey.Size      = new Size(370, 22);
        tipKey.BackColor = Color.Transparent;
        tipBox.Controls.Add(tipKey);

        Label tipTray = new Label();
        tipTray.Text      = "程序运行于系统托盘，右键托盘图标可查看更多选项。";
        tipTray.ForeColor = Color.FromArgb(100, 92, 66);
        tipTray.Font      = new Font("Microsoft YaHei UI", 8.5f);
        tipTray.Location  = new Point(16, 36);
        tipTray.Size      = new Size(370, 20);
        tipTray.BackColor = Color.Transparent;
        tipBox.Controls.Add(tipTray);

        // 开始使用按钮
        Button startBtn = new Button();
        startBtn.Text      = "开始使用  →";
        startBtn.ForeColor = Color.FromArgb(28, 26, 20);
        startBtn.BackColor = Color.FromArgb(192, 144, 48);
        startBtn.FlatStyle = FlatStyle.Flat;
        startBtn.FlatAppearance.BorderSize            = 0;
        startBtn.FlatAppearance.MouseOverBackColor    = Color.FromArgb(210, 164, 68);
        startBtn.Font      = new Font("Microsoft YaHei UI", 10, FontStyle.Bold);
        startBtn.Location  = new Point(168, 226);
        startBtn.Size      = new Size(200, 36);
        startBtn.Cursor    = Cursors.Hand;
        startBtn.Click    += delegate { Close(); };
        _donePanel.Controls.Add(startBtn);

        // ── 模拟进度定时器（UI 线程） ────────────────────────────────
        _ticker = new System.Windows.Forms.Timer();
        _ticker.Interval = 120;
        _ticker.Tick += OnTick;
    }

    // 进度条动画：每 120ms 向目标值靠近 1-3 格
    void OnTick(object sender, EventArgs e)
    {
        if (_activePb == null) return;
        int cur = _activePb.Value;
        if (cur >= _tickTarget) return;
        int gap = _tickTarget - cur;
        int step = gap > 20 ? 3 : gap > 8 ? 2 : 1;
        _activePb.Value = Math.Min(cur + step, _tickTarget);
    }

    // ── 辅助工厂 ────────────────────────────────────────────────────
    Label MakeLabel(string text, int x, int y, int w, Font f, Color c)
    {
        Label l = new Label();
        l.Text      = text;
        l.Font      = f;
        l.ForeColor = c;
        l.Location  = new Point(x, y);
        l.Size      = new Size(w, f.Height + 8);
        l.BackColor = Color.Transparent;
        return l;
    }

    ProgressBar MakeProgressBar(int x, int y, int w)
    {
        ProgressBar pb = new ProgressBar();
        pb.Location = new Point(x, y);
        pb.Size     = new Size(w, 14);
        pb.Minimum  = 0;
        pb.Maximum  = 100;
        pb.Value    = 0;
        pb.Style    = ProgressBarStyle.Continuous;
        return pb;
    }

    void OnLoad(object sender, EventArgs e)
    {
        _activePb = _pbStep1;
        _tickTarget = 0;
        _ticker.Start();
        Thread t = new Thread(DoInstall);
        t.IsBackground = true;
        t.Start();
    }

    // ── 跨线程 UI 更新 ──────────────────────────────────────────────
    void SetStatus(string text)
    {
        Invoke(new Action(delegate { _statusLabel.Text = text; }));
    }

    void Log(string line)
    {
        string l = line;
        Invoke(new Action(delegate
        {
            _log.AppendText(l + "\n");
            _log.ScrollToCaret();
        }));
    }

    // 平滑推进进度条到目标值（在后台线程调用，通过 _tickTarget 驱动 timer）
    void AdvanceTo(int target)
    {
        Invoke(new Action(delegate { _tickTarget = target; }));
        // 等待动画追上来
        while (true)
        {
            int cur = 0;
            Invoke(new Action(delegate { cur = _activePb.Value; }));
            if (cur >= target) break;
            Thread.Sleep(60);
        }
    }

    // 切换到步骤 2 的进度条
    void SwitchToStep2()
    {
        Invoke(new Action(delegate
        {
            _pbStep1.Value = 100;   // 步骤 1 满格
            _step1Lbl.ForeColor = Color.FromArgb(80, 160, 80);  // 变绿
            _step2Lbl.ForeColor = Color.FromArgb(192, 144, 48); // 激活步骤 2
            _activePb    = _pbStep2;
            _tickTarget  = 0;
        }));
    }

    // 安装完成，原地切换 UI
    void ShowDoneUI()
    {
        Invoke(new Action(delegate
        {
            _ticker.Stop();
            _pbStep1.Value = 100;
            _pbStep2.Value = 100;
            _step1Lbl.ForeColor = Color.FromArgb(80, 160, 80);
            _step2Lbl.ForeColor = Color.FromArgb(80, 160, 80);
            _statusLabel.Text    = "点击下方按钮启动 OpenHam";
            _log.Visible         = false;
            _donePanel.Visible   = true;
        }));
    }

    // ── 安装逻辑（后台线程） ────────────────────────────────────────
    void DoInstall()
    {
        // ─ Step 1: pip ─────────────────────────────────────────────
        SetStatus("正在从网络下载并安装 pip…");
        AdvanceTo(20);   // 启动前先推一点，表示正在工作

        string getPip = Path.Combine(_base, "runtime", "get-pip.py");
        int code = Exec(_python, "\"" + getPip + "\"");
        if (code != 0)
        {
            ShowError("pip 安装失败（退出码 " + code + "），请检查网络连接后重试。");
            return;
        }
        AdvanceTo(100);   // pip 完成 → 步骤 1 满格

        // ─ Step 2: requirements ────────────────────────────────────
        SetStatus("正在安装 PyQt6、keyboard 等依赖（可能需要几分钟）…");
        SwitchToStep2();
        AdvanceTo(15);   // 同上，先推一点

        string reqs = Path.Combine(_base, "requirements.txt");
        code = Exec(_python, "-m pip install -r \"" + reqs + "\"");
        if (code != 0)
        {
            ShowError("依赖安装失败（退出码 " + code + "），请检查网络连接后重试。");
            return;
        }
        AdvanceTo(100);   // 依赖完成 → 步骤 2 满格

        // ─ 完成 ────────────────────────────────────────────────────
        Success = true;
        Thread.Sleep(200);
        ShowDoneUI();
    }

    int Exec(string exe, string args)
    {
        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName               = exe;
        psi.Arguments              = args;
        psi.WorkingDirectory       = _base;
        psi.UseShellExecute        = false;
        psi.CreateNoWindow         = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError  = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding  = Encoding.UTF8;

        Process p = Process.Start(psi);
        p.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            { if (e.Data != null) Log(e.Data); };
        p.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            { if (e.Data != null) Log(e.Data); };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        p.WaitForExit();

        // 进程结束后让进度条快速飙到接近满格（实际满格在调用处设置）
        Invoke(new Action(delegate { _tickTarget = 96; }));
        return p.ExitCode;
    }

    void ShowError(string msg)
    {
        string m = msg;
        Invoke(new Action(delegate
        {
            _ticker.Stop();
            _stepLabel_SetError();
            _statusLabel.Text = "请关闭此窗口后重试";
            MessageBox.Show(m, "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }));
    }

    // 步骤标签引用（用于错误提示）
    void _stepLabel_SetError()
    {
        if (_activePb == _pbStep1)
            _step1Lbl.ForeColor = Color.FromArgb(200, 80, 80);
        else
            _step2Lbl.ForeColor = Color.FromArgb(200, 80, 80);
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        base.OnFormClosed(e);
        _ticker.Stop();
    }
}
