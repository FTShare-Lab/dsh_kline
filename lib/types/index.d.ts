import type { IncomingMessage, ServerResponse } from 'node:http';
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
}
export declare function apply(ctx: WebServerContext): void;
export {};
