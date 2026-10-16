import type { IncomingMessage, ServerResponse } from 'node:http';
import { type FtshareSettingsService } from './ftshare-settings-bridge.ts';
export declare const name = "dsh-kline-sidebar";
export declare const inject: string[];
interface WebServerContext {
    effect(callback: () => () => void, label: string): void;
    inject?(deps: string[], callback: (ctx: WebServerContext) => void): unknown;
    systemPrompt?: {
        context(input: {
            name: string;
            order: number;
            text: (context: any) => string;
        }): () => void;
    };
    ftshareSettings?: FtshareSettingsService;
    webServer: {
        register(route: {
            kind: 'prefix';
            path: string;
            handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>;
        }): () => void;
    };
}
export declare function apply(ctx: WebServerContext): void;
export declare function runtimeDirectory(env?: NodeJS.ProcessEnv): string;
export {};
