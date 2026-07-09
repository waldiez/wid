#!/usr/bin/env node

import { main } from "./cli/commands";

// Set exitCode instead of calling process.exit(): exit() can truncate stdout
// still buffered on a pipe; exitCode lets the event loop drain first.
process.exitCode = main();
