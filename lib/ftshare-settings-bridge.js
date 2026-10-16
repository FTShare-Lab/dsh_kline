/**
 * Bridge the DSH FTShare settings credential into the MCP server's process.
 *
 * The Key and every FTShare request live in different processes: the DSH host
 * owns the saved credential through the `ftshareSettings` service, while the
 * Python MCP server owns the requests and can only read a credential from its
 * environment or a file.  This module closes that seam with the smallest
 * contract both sides already share — one `0600` JSON file inside the runtime
 * directory, pointed at by the launcher, re-read before each request, so a Key
 * change applies without restarting the MCP server.
 *
 * Everything here is optional by construction: a host without the
 * `ftshareSettings` service never starts the bridge, no file is written, and
 * the MCP server keeps resolving credentials exactly as it did before.
 */
import { chmod, lstat, mkdir, mkdtemp, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
/** Environment variable naming the bridge file for the Python MCP server. */
export const SETTINGS_CREDENTIAL_ENV = 'DSH_KLINE_SETTINGS_KEY_FILE';
/** Directory, relative to the runtime directory, owned by the host bridge. */
export const CREDENTIAL_DIRECTORY = 'credentials';
const CREDENTIAL_FILE_PATTERN = /^ftshare-(\d+)\.json$/u;
const MAX_KEY_LENGTH = 512;
/**
 * Path of the credential file published by the DSH host.
 *
 * The launcher mirrors this rule in `scripts/run-dsh-kline.mjs`; keeping the
 * owner pid in the name means a file left behind by an earlier host can never
 * be read by a later one.
 */
export function settingsCredentialFile(runtimeDirectory, hostPid) {
    return join(runtimeDirectory, CREDENTIAL_DIRECTORY, `ftshare-${hostPid}.json`);
}
/**
 * Follow the settings credential until the returned bridge is disposed.
 *
 * The current Key is published immediately and re-published on every
 * invalidation; clearing the Key removes the file.  Failures are reported to
 * `warn` and otherwise ignored: a credential convenience must never take the
 * chart down.
 */
export function startFtshareSettingsBridge(options) {
    const hostPid = options.hostPid ?? process.pid;
    if (!Number.isSafeInteger(hostPid) || hostPid <= 0)
        throw new Error('invalid host process id');
    const file = settingsCredentialFile(options.runtimeDirectory, hostPid);
    const directory = dirname(file);
    let pending = Promise.resolve();
    let disposed = false;
    const sync = async () => {
        const key = usableKey(await options.settings.apiKey.resolve());
        if (disposed)
            return;
        if (key)
            await writeCredentialFile(file, key);
        else
            await withdrawCredentialFile(file);
    };
    const schedule = () => {
        pending = pending.then(sync, sync).catch(async () => {
            // Failed resolution/rotation must not leave a previously published key
            // active. Never include provider exception text: it may contain a key.
            await withdrawCredentialFile(file).catch(() => { });
            try {
                options.warn?.('FTShare settings credential publication failed');
            }
            catch { }
        });
        return pending;
    };
    const unsubscribe = options.settings.apiKey.subscribe(() => { void schedule(); });
    void pruneCredentialDirectory(directory, hostPid).catch(() => { });
    void schedule();
    return {
        async dispose() {
            disposed = true;
            unsubscribe();
            await pending.catch(() => { });
            await withdrawCredentialFile(file).catch(() => { });
        },
    };
}
/** Reject anything the Python reader would discard, so both sides agree. */
function usableKey(value) {
    const key = typeof value === 'string' ? value.trim() : '';
    if (!key || key.length > MAX_KEY_LENGTH)
        return '';
    for (const character of key) {
        const code = character.codePointAt(0) ?? 0;
        if (code < 32 || code === 127)
            return '';
    }
    return key;
}
async function writeCredentialFile(file, key) {
    const directory = dirname(file);
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink())
        throw new Error('unsafe credential directory');
    await restrict(directory, 0o700);
    // Exclusive random directory prevents following a pre-created temporary
    // symlink and keeps concurrent publishers from sharing a staging file.
    const staging = await mkdtemp(join(directory, `.${basename(file)}.`));
    const temporary = join(staging, 'credential.json');
    try {
        await restrict(staging, 0o700);
        await writeFile(temporary, JSON.stringify({ version: 1, api_key: key }), { mode: 0o600, flag: 'wx' });
        await restrict(temporary, 0o600);
        await rename(temporary, file);
        await restrict(file, 0o600);
    }
    finally {
        await rm(staging, { recursive: true, force: true }).catch(() => { });
    }
}
/** Drop files owned by hosts that are gone; a stale Key must not linger. */
async function pruneCredentialDirectory(directory, keepPid) {
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink())
        return;
    for (const name of await readdir(directory)) {
        const match = CREDENTIAL_FILE_PATTERN.exec(name);
        if (!match)
            continue;
        const pid = Number(match[1]);
        if (pid === keepPid || !Number.isSafeInteger(pid) || pid <= 0 || isAlive(pid))
            continue;
        await rm(join(directory, name), { force: true });
    }
}
async function withdrawCredentialFile(file) {
    try {
        const info = await lstat(dirname(file));
        if (!info.isDirectory() || info.isSymbolicLink())
            throw new Error('unsafe credential directory');
        await rm(file, { force: true });
    }
    catch (error) {
        if (error.code !== 'ENOENT')
            throw error;
    }
}
function isAlive(pid) {
    try {
        process.kill(pid, 0);
        return true;
    }
    catch (error) {
        // A live process owned by someone else is still a live process.
        return error.code === 'EPERM';
    }
}
async function restrict(path, mode) {
    // Windows has no POSIX mode bits; the Python reader only enforces them there
    // as well, so a platform that cannot apply them is not an error.
    if (process.platform !== 'win32')
        await chmod(path, mode);
}
