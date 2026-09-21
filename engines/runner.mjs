import { calculate } from './charts.mjs';
let text='';
for await (const chunk of process.stdin) {
  text+=chunk;
  if(text.length>16384) throw new Error('Input too large');
}
try {
  process.stdout.write(JSON.stringify(calculate(JSON.parse(text))));
} catch {
  // Never echo a birth record into a process log.
  process.stderr.write('Chart calculation failed\n');
  process.exitCode=1;
}
