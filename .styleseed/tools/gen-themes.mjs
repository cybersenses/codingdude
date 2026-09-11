// Regenerate CodingDude's dual-theme palette from the locked key color.
// Uses the installed StyleSeed palette engine (same module the resolver uses).
// Run:  node .styleseed/tools/gen-themes.mjs
import { writeFileSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const engine = join(
  homedir(), '.codingdude', 'skills', 'ss-resolve', 'scripts', 'palette-generator.mjs'
)
const { generatePalette, generatePaletteCss } = await import(pathToFileURL(engine).href)

// Must mirror STYLESEED.md (brand -> lock).
const base = { keyColor: '#ED7D31', character: 'balanced', harmony: 'auto', temperature: 'warm' }

mkdirSync('.styleseed/palettes', { recursive: true })
for (const mode of ['dark', 'light']) {
  const result = generatePalette({ ...base, mode })
  writeFileSync(`.styleseed/palettes/${mode}.css`, generatePaletteCss(result) + '\n')
  writeFileSync(`.styleseed/palettes/${mode}.json`, JSON.stringify(result, null, 2) + '\n')
  const r = result.roles
  console.log(
    `${mode}: primary=${r.primary} bg=${r.background} surface=${r.surface} ` +
      `fg=${r.foreground} accent=${r.accent}`
  )
}
