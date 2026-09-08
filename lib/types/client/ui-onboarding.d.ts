export declare const ONBOARDING_KEY = "dsh-kline:onboarding-version:v2";
export declare function hasPreviousUsage(storage: Storage): boolean;
export declare function captureOnboarding(storage?: Storage): void;
export declare function onboardingKind(storage?: Storage): 'upgrade' | 'first' | 'none';
export declare function classifyOnboarding(storage: Storage, previousUsage: boolean): 'upgrade' | 'first' | 'none';
export declare function acknowledgeOnboarding(storage?: Storage): void;
