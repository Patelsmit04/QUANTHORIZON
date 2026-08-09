// Quick diagnostic: what's the actual state of sections when we try to switch?
const http = require('http');

http.get('http://127.0.0.1:8000/static/app.js?v=10.0.0', (res) => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
        console.log('Total bytes:', data.length);
        const lines = data.split('\n');
        console.log('Total lines:', lines.length);
        
        // Check if switchSection is present and correct
        const switchIdx = lines.findIndex(l => l.includes('function switchSection'));
        console.log('\nswitchSection at line:', switchIdx + 1);
        if (switchIdx >= 0) {
            for (let i = switchIdx; i < switchIdx + 30 && i < lines.length; i++) {
                console.log(`${i+1}: ${lines[i].trimEnd()}`);
            }
        }
        
        // Check if historySection variable is declared
        const histIdx = lines.findIndex(l => l.includes('historySection') && l.includes('getElementById'));
        console.log('\nhistorySection declared at line:', histIdx + 1);
        if (histIdx >= 0) console.log(lines[histIdx].trim());
        
        // Check for any syntax errors near our edits
        const collapsedIdx = lines.findIndex(l => l.includes('collapsedStrategyIds'));
        console.log('\ncollapsedStrategyIds at line:', collapsedIdx + 1);
        if (collapsedIdx >= 0) console.log(lines[collapsedIdx].trim());
    });
}).on('error', e => console.error(e));
