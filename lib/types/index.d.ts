import type { IncomingMessage, ServerResponse } from 'node:http';
import { type FtshareSettingsService } from './ftshare-settings-bridge.ts';
export declare const name = "dsh-kline-sidebar";
export declare const inject: string[];
interface WebServerContext {
    effect(callback: () => () => void, label: string): void;
    webServer: {
        register(route: {
            kind: 'prefix';
            path: string;
            handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>;
        }): () => void;
    };
    /**
     * Cordis runs the callback once every listed service is available, and tears
     * the nested fiber down when one disappears.  Optional here because a host
     * without the FTShare settings plugin — and every test stub — omits it.
     */
    inject?(inject: string[], callback: (ctx: SettingsContext) => void): unknown;
}
interface SettingsContext {
    effect(callback: () => () => void, label: string): void;
    ftshareSettings: FtshareSettingsService;
}
export declare function apply(ctx: WebServerContext): void;
export declare function runtimeDirectory(env?: NodeJS.ProcessEnv): string;
export {};
