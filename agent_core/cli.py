"""Typer CLI: job-agent entrypoint."""

import asyncio
import logging
import sys

import typer

app = typer.Typer(name="job-agent", help="求职 AI Agent")
logger = logging.getLogger("agent_core")


def _setup(config_path="config.yaml"):
    from agent_core.config import load_config
    from agent_core.llm.providers import create_provider
    from agent_core.storage.db import get_db, migrate

    # Ensure UTF-8 output on Windows (emojis break GBK in cmd.exe)
    if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("data/agent.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    config = load_config(config_path)
    db = get_db()
    migrate(db)
    # Tolerate missing API key: non-LLM commands (login, search, status) still
    # work without it. LLM commands call _require_provider() for a clear error.
    provider = create_provider(config) if config.api_key else None
    if provider is None and config.api_key == "":
        logger.warning(f"{config.llm.api_key_env} not set — LLM commands unavailable")
    return config, db, provider


def _require_provider(provider, config):
    """Guard for commands that need the LLM. Gives a clear error instead of NoneType crash."""
    if provider is None:
        raise typer.Exit(
            f"LLM unavailable: set {config.llm.api_key_env} environment variable "
            f'(e.g. setx {config.llm.api_key_env} "sk-your-key").'
        )
    return provider


@app.command()
def login(
    platform: str = typer.Option("", "--platform", help="Platform: boss, liepin"),
    status: bool = typer.Option(False, "--status", help="Check login status"),
):
    """Launch Playwright browser for manual login, or check session status."""
    config, _, _ = _setup()

    # Accept short aliases documented in help/README (boss -> boss_zhipin)
    _ALIASES = {
        "boss": "boss_zhipin",
        "liepin": "liepin",
        "51": "job51",
        "zhipin": "boss_zhipin",
        "zl": "zhilian",
    }
    platform = _ALIASES.get(platform, platform)

    if status:
        from pathlib import Path

        for pname, pc in config.platforms.items():
            if not pc.enabled:
                continue
            cookie_file = Path(pc.cookie_path)
            if cookie_file.exists():
                import datetime
                import json

                with open(cookie_file) as f:
                    cookies = json.load(f)
                # Check if any cookie has expired
                now_ms = datetime.datetime.now().timestamp()
                expired = [c for c in cookies if c.get("expires", -1) > 0 and c["expires"] < now_ms]
                valid_n = len(cookies) - len(expired)
                typer.echo(
                    f"  {pname}: {len(cookies)} cookies, {valid_n} valid, "
                    f"{len(expired)} expired"
                )
            else:
                typer.echo(f"  {pname}: NOT LOGGED IN (no cookie file)")
        return

    if not platform:
        typer.echo("Use --platform boss|liepin|zhilian to login, or --status to check.")
        return
    if platform not in config.platforms:
        typer.echo(f"Unknown platform: {platform}")
        raise typer.Exit(1)

    import asyncio

    async def _do_login():
        if platform == "boss_zhipin":
            from agent_core.platforms.boss_zhipin import boss_login

            await boss_login(config.platforms[platform].cookie_path)
        elif platform == "liepin":
            from agent_core.platforms.liepin import liepin_login

            await liepin_login(config.platforms[platform].cookie_path)
        elif platform == "zhilian":
            from agent_core.platforms.zhilian import zhilian_login

            await zhilian_login(config.platforms[platform].cookie_path)
        else:
            typer.echo(f"Login not yet implemented for {platform}")

    asyncio.run(_do_login())


@app.command()
def rematch(
    job_id: str = typer.Argument("", help="Job ID to rematch"),
    all_since: str = typer.Option("", "--all-since", help="Date YYYY-MM-DD"),
):
    """Re-run matching for a job or all jobs since a date (after resume update)."""
    config, db, provider = _setup()
    if job_id:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            typer.echo(f"Job not found: {job_id}")
            return
        from agent_core.platforms.base import Job

        job = Job.from_storage(row)
        # Enrich with full JD on-demand (single job only, not batch)
        import asyncio

        from agent_core.platforms.enrichment import enrich_job_jd

        job = asyncio.run(enrich_job_jd(job, config))
        # Re-run prescreen + match
        from agent_core.pipeline.match import match_jobs
        from agent_core.pipeline.prescreen import prescreen

        ps = prescreen([job], config)
        if ps:
            results, _skipped = asyncio.run(match_jobs(ps, config, provider))
            for r in results:
                typer.echo(
                    f"  {r['score']}% {r['job_title']} @ {r['company']}"
                    f" ({r.get('confidence', '?')})"
                )
                typer.echo(f"    {r['match_reason']}")
    elif all_since:
        rows = db.execute("SELECT * FROM jobs WHERE last_seen >= ?", (all_since,)).fetchall()
        if not rows:
            typer.echo(f"No jobs since {all_since}")
            return
        from agent_core.platforms.base import Job

        jobs = [Job.from_storage(dict(r)) for r in rows]
        import asyncio

        from agent_core.pipeline.match import match_jobs
        from agent_core.pipeline.prescreen import prescreen

        ps = prescreen(jobs, config)
        typer.echo(f"Re-matching {len(ps)} jobs since {all_since}...")
        results, _skipped = asyncio.run(match_jobs(ps, config, provider))
        for r in results[:10]:
            typer.echo(f"  {r['score']}% {r['job_title']} @ {r['company']}")
    else:
        typer.echo(
            "Usage: job-agent rematch <job-id>"
            "     OR     job-agent rematch --all-since 2026-06-01"
        )


@app.command()
def search(
    direction: str = typer.Option("", "--direction"),
    platforms: str = typer.Option("", "--platforms"),
):
    """Search jobs across platforms."""
    config, _, _ = _setup()
    dirs = [direction] if direction else None
    plats = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None

    async def _run():
        from agent_core.pipeline.search import search_all

        jobs = await search_all(config, plats, dirs)
        typer.echo(f"Found {len(jobs)} jobs")
        for j in jobs[:20]:
            typer.echo(f"  [{j.direction}] {j.title} @ {j.company} ({j.location})")

        # If zero results, check cookies and print diagnosis
        if len(jobs) == 0 and config.platforms:
            from agent_core.cookie_health import diagnose_empty_results

            diag = diagnose_empty_results(config)
            if diag:
                typer.echo(diag)

        return jobs

    return asyncio.run(_run())


@app.command()
def pipeline(stages: str = typer.Option("search,filter,prescreen,match", "--stages")):
    """Run full or partial pipeline."""
    config, _, provider = _setup()
    stage_list = [s.strip() for s in stages.split(",")]

    async def _run():
        from agent_core.pipeline.orchestrator import run_pipeline

        return await run_pipeline(config, provider, stages=stage_list)

    data = asyncio.run(_run())
    matched = data.get("matched", [])
    if matched:
        typer.echo("\nTop matches:")
        for m in matched[:10]:
            typer.echo(f"  {m['score']}% {m['job_title']} @ {m['company']}")
            typer.echo(f"    {m['match_reason']}")
    else:
        typer.echo("No results. Try 'job-agent search' first.")
        # Check if cookies are the root cause
        if config.platforms:
            from agent_core.cookie_health import diagnose_empty_results

            diag = diagnose_empty_results(config)
            if diag:
                typer.echo(diag)


@app.command()
def tailor(job_id: str = typer.Argument(..., help="Job ID to tailor resume for")):
    """Generate tailored resume (.docx + .md) for a job and open job link."""
    config, db, provider = _setup()
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"Tailoring resume for: {job.title} @ {job.company}")

    import asyncio

    from agent_core.pipeline.tailor import open_job_link, save_resume, tailor_resume
    from agent_core.platforms.enrichment import enrich_job_jd

    async def _run():
        # Enrich with full JD on-demand before tailoring
        enriched = await enrich_job_jd(job, config)
        text = await tailor_resume(enriched, config, provider)
        paths = save_resume(text, enriched)
        typer.echo(f"Resume saved: {paths['docx']}")
        typer.echo(f"Preview:     {paths['md']}")
        open_job_link(enriched)

    asyncio.run(_run())


@app.command()
def serve(port: int = typer.Option(8765, "--port")):
    """Start local HTTP dashboard."""
    from agent_core.server.serve import start_server

    start_server(port=port)


@app.command()
def track(
    action: str = typer.Argument("list"),
    target: str = typer.Argument("", help="job-id or app-id or external-url"),
    status: str = typer.Option("", "--status", help="Filter status or set new status"),
):
    """Track: add <job-id|url>, list [--status HR已读], show <id>, update <id> --status 二面."""
    _, db, _ = _setup()
    from agent_core.tracking.tracker import (
        add_application,
        create_timeline_table,
        get_application,
        get_timeline,
        list_applications,
        update_status,
    )

    create_timeline_table(db)

    if action == "add":
        if not target:
            typer.echo("Usage: job-agent track add <job-id-or-url>")
            return
        # Support external applications: if target is a URL, generate an ID
        import hashlib

        jid = (
            target
            if not target.startswith("http")
            else hashlib.md5(target.encode()).hexdigest()[:16]  # nosec B324 -- job ID, not security
        )
        aid = add_application(db, jid)
        typer.echo(f"Application #{aid} recorded (已投递)")

    elif action == "update":
        if not target or not status:
            typer.echo("Usage: job-agent track update <app-id> --status 二面")
            return
        try:
            update_status(db, int(target), status)
            typer.echo(f"#{target} -> {status}")
        except ValueError as e:
            typer.echo(f"Error: {e}")

    elif action == "show":
        if not target:
            typer.echo("Usage: job-agent track show <app-id>")
            return
        try:
            app = get_application(db, int(target))
            typer.echo(
                f"#{app['id']} [{app['status']}]"
                f" {app.get('job_title', '?')} @ {app.get('job_company', '?')}"
            )
            typer.echo(f"  Applied: {app['applied_at']} | Updated: {app['updated_at']}")
            # Timeline
            tl = get_timeline(db, int(target))
            if tl:
                typer.echo("  Timeline:")
                for t in tl:
                    typer.echo(f"    {t['created_at']}: {t['from_status']} -> {t['to_status']}")
        except ValueError as e:
            typer.echo(f"Error: {e}")

    elif action == "list":
        status_filter = status if status else None
        apps = list_applications(db, status_filter)
        if not apps:
            label = f" (filtered by '{status}')" if status else ""
            typer.echo(f"No applications{label}.")
            return
        for a in apps:
            m = {"Offer": "🟢", "入职": "🟢", "已终止": "🔴"}.get(a["status"], "🟡")
            typer.echo(
                f"  {m} #{a['id']} [{a['status']}]"
                f" {a.get('job_title', '?')} @ {a.get('job_company', '?')}"
            )
    else:
        typer.echo(f"Unknown: {action}. Try: list, add, show, update")


@app.command()
def cover_letter(job_id: str = typer.Argument(..., help="Job ID")):
    """Generate a cover letter for a job."""
    config, db, provider = _setup()
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"Cover letter: {job.title} @ {job.company}")
    import asyncio

    from agent_core.pipeline.cover_letter import generate_cover_letter, save_cover_letter
    from agent_core.platforms.enrichment import enrich_job_jd

    async def _r():
        # Enrich with full JD on-demand before generating cover letter
        enriched = await enrich_job_jd(job, config)
        text = await generate_cover_letter(enriched, config, provider)
        path = save_cover_letter(text, enriched)
        typer.echo(text[:200] + "...")
        typer.echo(f"Saved: {path}")

    asyncio.run(_r())


@app.command()
def interview_prep(job_id: str = typer.Argument(..., help="Job ID")):
    """Generate interview prep questions and save to output/."""
    config, db, provider = _setup()
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"Interview prep: {job.title} @ {job.company}")
    import asyncio

    from agent_core.pipeline.interview_prep import predict_questions, save_interview_prep
    from agent_core.platforms.enrichment import enrich_job_jd

    async def _r():
        # Enrich with full JD on-demand before generating interview prep
        enriched = await enrich_job_jd(job, config)
        qs = await predict_questions(enriched, config, provider)
        p = save_interview_prep(qs, enriched)
        categories = ("technical", "behavioral", "project")
        total_q = sum(len(qs.get(c, [])) for c in categories)
        typer.echo(f"Saved: {p}\nTotal: {total_q} questions")

    asyncio.run(_r())


@app.command()
def mock_interview(job_id: str = typer.Argument(..., help="Job ID")):
    """Start an interactive mock interview in the terminal."""
    config, db, provider = _setup()
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    from agent_core.pipeline.interview_prep import mock_interview as mi

    mi(job, config, provider)


@app.command()
def offer_eval(
    company: str = typer.Option(..., "--company"),
    title: str = typer.Option("", "--title"),
    location: str = typer.Option("", "--location"),
    salary: str = typer.Option("", "--salary"),
    bonus: str = typer.Option("", "--bonus"),
    benefits: str = typer.Option("", "--benefits"),
    level: str = typer.Option("", "--level"),
    notes: str = typer.Option("", "--notes"),
):
    """Evaluate a job offer."""
    config, _, provider = _setup()
    import asyncio

    from agent_core.pipeline.offer_eval import evaluate

    async def _r():
        r = await evaluate(
            config, provider, company, title, location, salary, bonus, benefits, level, notes
        )
        typer.echo(f"\n综合评价: {r['overall_score']}/10")
        typer.echo(
            f"竞争力: {r['competitive_score']}/10"
            f" | 成长性: {r['growth_score']}/10"
            f" | 风险: {r['risk_score']}/10"
        )
        typer.echo(f"\n{r['summary']}\n")
        typer.echo("优势:")
        for p in r.get("pros", []):
            typer.echo(f"  + {p}")
        typer.echo("劣势:")
        for c in r.get("cons", []):
            typer.echo(f"  - {c}")
        if r.get("negotiation_levers"):
            typer.echo("谈判杠杆:")
            for n in r["negotiation_levers"]:
                typer.echo(f"  > {n}")

    asyncio.run(_r())


@app.command()
def salary_advice(
    company: str = typer.Option(..., "--company"),
    title: str = typer.Option("", "--title"),
    salary: str = typer.Option("", "--salary"),
    target: str = typer.Option("", "--target"),
    strengths: str = typer.Option("", "--strengths"),
    context: str = typer.Option("", "--context"),
):
    """Get salary negotiation strategy."""
    config, _, provider = _setup()
    import asyncio

    from agent_core.pipeline.salary_advice import get_advice

    async def _r():
        r = await get_advice(config, provider, company, title, salary, target, strengths, context)
        typer.echo(f"\n锚点: {r['anchor']}")
        typer.echo(f"自信度: {r['confidence']}")
        typer.echo("筹码:")
        for line in r.get("leverage", []):
            typer.echo(f"  > {line}")
        typer.echo("让步方案:")
        for c in r.get("concessions", []):
            typer.echo(f"  - {c}")
        typer.echo("话术:")
        for s in r.get("scripts", []):
            typer.echo(f'  "{s}"')

    asyncio.run(_r())


@app.command(name="import-cookies")
def import_cookies_cmd(
    export_file: str = typer.Argument(..., help="浏览器导出的 cookie JSON 路径"),
    platform: str = typer.Argument(..., help="目标平台键，如 boss_zhipin"),
    domain: str = typer.Option("", "--domain", help="按域名子串过滤 cookie"),
):
    """Convert a browser-exported cookie JSON into the project cookie file."""
    from agent_core.platforms.cookie_utils import convert_and_save

    try:
        r = convert_and_save(export_file, platform, domain)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"[FAIL] {e}")
        raise typer.Exit(1)
    typer.echo(f"[OK] {r['count']} cookies -> {r['out_path']}")
    if r["session_found"]:
        typer.echo(f"     session cookies: {r['session_found']}")
        typer.echo("     [OK] 登录态 cookie 存在。")
    else:
        typer.echo("     [WARN] 未发现已知 session cookie，请确认导出前已登录。")


@app.command(name="check-cookies")
def check_cookies_cmd(
    probe: bool = typer.Option(
        False, "--probe", help="实际发搜索请求探活（默认关闭，避免消耗 Boss token）"
    ),
    config_path: str = typer.Option("config.yaml", "--config"),
):
    """体检各平台 cookie 健康状态（过期检查 + 重抓指引）。"""
    config, _, _ = _setup(config_path)

    import asyncio

    from agent_core.cookie_health import CookieStatus, check_cookies

    async def _run():
        return await check_cookies(config, probe=probe)

    results = asyncio.run(_run())

    # Table header
    header = f" {'平台':<10s} {'状态':<12s} {'关键Cookie过期时间'}"
    typer.echo()
    typer.echo(header)
    typer.echo("-" * 58)

    for r in results:
        expiry_info = "; ".join(r.details) if r.details else "N/A"
        line = f" {r.status_icon} {r.display_name:<8s} {r.status_label:<10s} {expiry_info}"
        typer.echo(line)

    typer.echo()

    # Print regrab guides for problem platforms
    problem_platforms = [
        r
        for r in results
        if r.status in (CookieStatus.EXPIRED, CookieStatus.MISSING, CookieStatus.EXPIRING_SOON)
    ]

    if problem_platforms:
        typer.echo("需要重抓 cookie 的平台：")
        for r in problem_platforms:
            typer.echo(r.regrab_guide)
        typer.echo()

    if probe:
        typer.echo("[--probe] 探活完成。" " 注意：Boss token 短效，探活会消耗一次请求额度。")
    else:
        typer.echo("[提示] 仅检查文件+过期时间，未实际探活。" " 加 --probe 可发请求验证。")


@app.command()
def schedule(action: str = typer.Argument("status")):
    """Manage scheduled search: on, off, status."""
    config, db, provider = _setup()
    from agent_core.scheduler.scheduler import (
        acquire_lock,
        release_lock,
        schedule_off,
        schedule_on,
        schedule_status,
    )

    if action == "on":
        schedule_on(config)
        typer.echo("Scheduler ON." " Run 'job-agent schedule run' to start daemon.")
    elif action == "off":
        schedule_off()
        typer.echo("Scheduler OFF")
    elif action == "run":
        schedule_on(config)
        if not acquire_lock():
            typer.echo("Another scheduler daemon is already running. Aborting.")
            return
        typer.echo(
            f"Starting daemon (every {config.schedule.interval_hours}h,"
            f" quiet {config.schedule.quiet_hours})"
        )
        typer.echo("Press Ctrl+C to stop.")
        import asyncio

        async def _daemon():
            while True:
                from agent_core.scheduler.scheduler import run_scheduled_search

                await run_scheduled_search(config, provider, db)
                await asyncio.sleep(config.schedule.interval_hours * 3600)

        try:
            asyncio.run(_daemon())
        except KeyboardInterrupt:
            typer.echo("Daemon stopped.")
        finally:
            release_lock()
    else:
        s = schedule_status()
        typer.echo(
            f"Enabled: {s['enabled']} | Runs: {s['runs']}" f" | Last: {s.get('last_run', 'never')}"
        )
        if s.get("last_error"):
            typer.echo(f"Last error: {s['last_error']}")
        typer.echo("Commands: on | off | run | status")


if __name__ == "__main__":
    app()
