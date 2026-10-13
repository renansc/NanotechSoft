const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/riob/source/script.js', 'utf8');
const ctx = vm.createContext({Intl});
vm.runInContext(source.slice(source.indexOf('function ordenarResultados('),
  source.indexOf('function _vendasPrecoPermitido(')), ctx);
const ordenar = ctx.ordenarResultados;
const ids = rows => Array.from(rows, row => row.id);
const example = Object.freeze([
  Object.freeze({id:'a', grupo:'PET 2L', cidade:'Londrina', valor:12.5}),
  Object.freeze({id:'b', grupo:'Agua', cidade:'Apucarana', valor:9}),
  Object.freeze({id:'c', grupo:'PET 2L', cidade:'Londrina', valor:null}),
]);
assert.deepEqual(ids(ordenar(example, 'valor')), ['b','a','c']);
assert.deepEqual(ids(ordenar(example, 'valor', 'desc')), ['a','b','c']);
assert.deepEqual(ids(ordenar(example, 'cidade')), ['b','a','c']);
assert.deepEqual(ids(ordenar(example, 'grupo')), ['b','a','c']);
assert.deepEqual(ids(example), ['a','b','c']);
assert.notEqual(ordenar(example, 'valor'), example);
assert.equal(ordenar(example, 'valor')[0], example[1]);

const values = [2,10,0,-1,2,null,undefined,NaN,Infinity,-Infinity,'0','10'].map((valor,id)=>({valor,id}));
assert.deepEqual(ids(ordenar(values,'valor')), [3,2,0,4,1,5,6,7,8,9,10,11]);
assert.deepEqual(ids(ordenar(values,'valor','desc')), [1,0,4,2,3,5,6,7,8,9,10,11]);
const names = ['Grupo 10','Grupo 2','Água','agua','','  ',null,undefined].map((grupo,id)=>({grupo,id}));
assert.deepEqual(ids(ordenar(names,'grupo')), [2,3,1,0,4,5,6,7]);
assert.deepEqual(ids(ordenar(names,'grupo','desc')), [0,1,2,3,4,5,6,7]);
for (const args of [[null,'valor'], [example,'id'], [example,'valor','up'], [example,null], [example,'valor',null]]) {
  assert.throws(()=>ordenar(...args), error => error.name==='TypeError');
}
assert.deepEqual(ids(ordenar([], 'valor')), []);

console.log('OK: ordenacao numerica/texto, zeros, ausentes, empates e imutabilidade');
