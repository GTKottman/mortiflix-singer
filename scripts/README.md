# Scripts

Each `.js` file here (and in `~/MortiflixSinger/scripts/`, for your own) shows up in the editor's Scripts menu.
A script is an ES module: `export const title = '...'` and `export default function (singer) { ... }`, where
`singer` is the editor's scripting API (`singer.project()`, `singer.track()`, `singer.edit(label, fn)`,
`singer.select(ids)`, `singer.render()`, `singer.app.sel` = the selected note ids...). Changes made inside
`singer.edit(label, (project) => { ... })` are one undo step.
