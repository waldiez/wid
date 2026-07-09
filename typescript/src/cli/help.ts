export function printHelp(): void {
  console.error(`wid - WID/HLC-WID generator CLI

Usage:
  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]
  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]
  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]
  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]
  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]
  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]

Canonical mode:
  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|null|stdout N=#
  wid A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=6] [MAX_AGE_SEC=0] [MAX_FUTURE_SEC=5]
  For A=stream: N=0 means infinite stream
  E supports: state | stateless | sql`);
}

export function printActions(): void {
  console.log(`wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp

Services (Rust implementation only -- see spec/SERVICES.md):
  A=start | A=stop | A=status | A=logs | A=run | A=discover | A=scaffold
  A=saf | A=saf-wid | A=wir | A=wism | A=wihp | A=wipr | A=duplex

Help:
  A=help-actions`);
}
