/** Environment variable naming the bridge file for the Python MCP server. */
export declare const SETTINGS_CREDENTIAL_ENV = "DSH_KLINE_SETTINGS_KEY_FILE";
/** Directory, relative to the runtime directory, owned by the host bridge. */
export declare const CREDENTIAL_DIRECTORY = "credentials";
/**
 * Structural view of the settings service this bridge depends on.
 *
 * Declared here instead of imported from the settings plugin so that a host
 * without that plugin needs no dependency, type, or build edge on it.
 */
export interface FtshareApiKeySettings {
    /** Current Key, `undefined` when nothing is configured. */
    resolve(): Promise<string | undefined>;
    /** Credential invalidation notification; returns an unsubscribe function. */
    subscribe(listener: () => void): () => void;
}
/** Host service name published by the DSH FTShare settings plugin. */
export interface FtshareSettingsService {
    readonly apiKey: FtshareApiKeySettings;
}
export interface FtshareSettingsBridgeOptions {
    settings: FtshareSettingsService;
    /** Runtime directory shared with the launcher and the MCP server. */
    runtimeDirectory: string;
    /** Owning DSH host process, matching the accompanying service locator. */
    hostPid?: number;
    /** Optional diagnostic sink; the bridge stays silent without one. */
    warn?: (message: string) => void;
}
export interface FtshareSettingsBridge {
    /** Stop following the credential and remove the published file. */
    dispose(): Promise<void>;
}
/**
 * Path of the credential file published by the DSH host.
 *
 * The launcher mirrors this rule in `scripts/run-dsh-kline.mjs`; keeping the
 * owner pid in the name means a file left behind by an earlier host can never
 * be read by a later one.
 */
export declare function settingsCredentialFile(runtimeDirectory: string, hostPid: number): string;
/**
 * Follow the settings credential until the returned bridge is disposed.
 *
 * The current Key is published immediately and re-published on every
 * invalidation; clearing the Key removes the file.  Failures are reported to
 * `warn` and otherwise ignored: a credential convenience must never take the
 * chart down.
 */
export declare function startFtshareSettingsBridge(options: FtshareSettingsBridgeOptions): FtshareSettingsBridge;
