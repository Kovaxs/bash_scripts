// Publish exact session metadata for the Bash spi command. No prompts or history.
import { execFileSync } from "node:child_process";
import { mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export default function (pi) {
    const directory = join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "spi");
    const file = join(directory, `${process.pid}.json`);
    const temporary = `${file}.tmp`;
    let started;
    let state = "idle";

    function publish(ctx) {
        if (!started) {
            started = execFileSync("ps", ["-p", String(process.pid), "-o", "lstart="], {
                encoding: "utf8", env: { ...process.env, LC_ALL: "C" }, timeout: 2000,
            }).trim().replace(/\s+/g, " ");
        }
        mkdirSync(directory, { recursive: true, mode: 0o700 });
        const metadata = {
            pid: process.pid,
            started,
            session_id: ctx.sessionManager.getSessionId(),
            session_name: ctx.sessionManager.getSessionName() || null,
            session_file: ctx.sessionManager.getSessionFile() || null,
            cwd: ctx.cwd,
            state,
            tmux_socket: process.env.TMUX?.replace(/,[^,]*,[^,]*$/, "") || null,
        };
        writeFileSync(temporary, `${JSON.stringify(metadata)}\n`, { mode: 0o600 });
        renameSync(temporary, file);
    }

    pi.on("session_start", (_event, ctx) => {
        state = ctx.isIdle() ? "idle" : "running";
        publish(ctx);
    });
    pi.on("session_info_changed", (_event, ctx) => publish(ctx));
    pi.on("agent_start", (_event, ctx) => {
        state = "running";
        publish(ctx);
    });
    pi.on("agent_settled", (_event, ctx) => {
        state = "idle";
        publish(ctx);
    });
    pi.on("ui_prompt_start", (_event, ctx) => {
        state = "waiting";
        publish(ctx);
    });
    pi.on("ui_prompt_end", (_event, ctx) => {
        state = ctx.isIdle() ? "idle" : "running";
        publish(ctx);
    });
    pi.on("session_shutdown", () => {
        rmSync(file, { force: true });
        rmSync(temporary, { force: true });
    });
}
