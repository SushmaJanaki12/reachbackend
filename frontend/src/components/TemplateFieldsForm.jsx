import { Link } from 'react-router-dom'
import { Field, Toggle } from './ui'

export const BLANK_TPL_FIELDS = {
  headline: '', opening_line: '',
  show_bullets: false, campaign_name: '',
  bullets: [{ label: '', text: '' }, { label: '', text: '' }, { label: '', text: '' }],
  show_callout: false, callout_label: '', callout_text: '',
  show_cta: false, action_url: '', action_label: '',
  show_badges: false,
  show_secondary: false, secondary_action_url: '', secondary_action_label: '',
}

function Block({ path, label, children, tf, getTplValue, setTplField, canEdit }) {
  return (
    <div className="field" style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
      <div className="flex between" style={{ marginBottom: getTplValue(path) || tf[path] ? 8 : 0 }}>
        <label style={{ marginBottom: 0 }}>{label}</label>
        <Toggle checked={!!tf[path]} onChange={(v) => setTplField(path, v)} title={canEdit ? undefined : 'View only'} />
      </div>
      {tf[path] && children}
    </div>
  )
}

export function TemplateFieldsForm({ project, tf, getTplValue, setTplField, tplRefs, tplFocused, canEdit }) {
  const bindRef = (path) => (el) => { tplRefs.current[path] = el }
  const onFocus = (path) => () => { tplFocused.current = path }

  return (
    <>
      <div className="field" style={{ background: 'var(--teal-soft2)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
        <div className="flex between">
          <div className="t-sub">Company &amp; sender branding (from Project settings)</div>
          <Link to="/projects" className="hint" style={{ textDecoration: 'underline' }}>Edit in Projects</Link>
        </div>
        <div className="t-strong" style={{ marginTop: 4 }}>{project?.name || '—'}</div>
        <div className="muted" style={{ fontSize: 12.5 }}>
          {project?.sender_name || 'No sender name set'}{project?.sender_designation ? ` · ${project.sender_designation}` : ''}
          {project?.company_website ? ` · ${project.company_website}` : ''}
        </div>
      </div>

      <Field label="Headline">
        <input ref={bindRef('headline')} className="input" value={getTplValue('headline')} disabled={!canEdit}
          onFocus={onFocus('headline')} onChange={(e) => setTplField('headline', e.target.value)}
          placeholder="Big news for {{Name}}" />
      </Field>
      <Field label="Opening line">
        <textarea ref={bindRef('opening_line')} className="textarea" style={{ minHeight: 70 }} value={getTplValue('opening_line')} disabled={!canEdit}
          onFocus={onFocus('opening_line')} onChange={(e) => setTplField('opening_line', e.target.value)}
          placeholder="Hope you're doing well, {{Name}}." />
      </Field>

      <Block path="show_bullets" label="Key takeaways (bullet list)" tf={tf} getTplValue={getTplValue} setTplField={setTplField} canEdit={canEdit}>
        <Field label="Intro line campaign name"><input className="input" value={getTplValue('campaign_name')} disabled={!canEdit}
          onFocus={onFocus('campaign_name')} onChange={(e) => setTplField('campaign_name', e.target.value)} placeholder="Autumn Launch" /></Field>
        {[0, 1, 2].map((i) => (
          <div className="row-2" key={i}>
            <Field label={`Bullet ${i + 1} label`}>
              <input ref={bindRef(`bullets.${i}.label`)} className="input" value={getTplValue(`bullets.${i}.label`)} disabled={!canEdit}
                onFocus={onFocus(`bullets.${i}.label`)} onChange={(e) => setTplField(`bullets.${i}.label`, e.target.value)} />
            </Field>
            <Field label={`Bullet ${i + 1} text`}>
              <input ref={bindRef(`bullets.${i}.text`)} className="input" value={getTplValue(`bullets.${i}.text`)} disabled={!canEdit}
                onFocus={onFocus(`bullets.${i}.text`)} onChange={(e) => setTplField(`bullets.${i}.text`, e.target.value)} />
            </Field>
          </div>
        ))}
      </Block>

      <Block path="show_callout" label="Callout / quick tip" tf={tf} getTplValue={getTplValue} setTplField={setTplField} canEdit={canEdit}>
        <div className="row-2">
          <Field label="Label"><input ref={bindRef('callout_label')} className="input" value={getTplValue('callout_label')} disabled={!canEdit}
            onFocus={onFocus('callout_label')} onChange={(e) => setTplField('callout_label', e.target.value)} placeholder="Tip" /></Field>
          <Field label="Text"><input ref={bindRef('callout_text')} className="input" value={getTplValue('callout_text')} disabled={!canEdit}
            onFocus={onFocus('callout_text')} onChange={(e) => setTplField('callout_text', e.target.value)} /></Field>
        </div>
      </Block>

      <Block path="show_cta" label="Call-to-action button" tf={tf} getTplValue={getTplValue} setTplField={setTplField} canEdit={canEdit}>
        <div className="row-2">
          <Field label="Button URL"><input className="input" value={getTplValue('action_url')} disabled={!canEdit}
            onChange={(e) => setTplField('action_url', e.target.value)} placeholder="https://…" /></Field>
          <Field label="Button label"><input ref={bindRef('action_label')} className="input" value={getTplValue('action_label')} disabled={!canEdit}
            onFocus={onFocus('action_label')} onChange={(e) => setTplField('action_label', e.target.value)} placeholder="Get started" /></Field>
        </div>
      </Block>

      <Block path="show_badges" label="Trust badges" tf={tf} getTplValue={getTplValue} setTplField={setTplField} canEdit={canEdit}>
        <p className="hint">Badge images are set once in Project → Configure → Branding.</p>
      </Block>

      <Block path="show_secondary" label="Secondary link" tf={tf} getTplValue={getTplValue} setTplField={setTplField} canEdit={canEdit}>
        <div className="row-2">
          <Field label="URL"><input className="input" value={getTplValue('secondary_action_url')} disabled={!canEdit}
            onChange={(e) => setTplField('secondary_action_url', e.target.value)} placeholder="https://…" /></Field>
          <Field label="Label"><input ref={bindRef('secondary_action_label')} className="input" value={getTplValue('secondary_action_label')} disabled={!canEdit}
            onFocus={onFocus('secondary_action_label')} onChange={(e) => setTplField('secondary_action_label', e.target.value)} placeholder="Learn more" /></Field>
        </div>
      </Block>
    </>
  )
}

/** Shared getter/setter pair for a `template_fields`-shaped object, used by
 * both the campaign content editor and the template library editor. */
export function useTplFieldAccessors(tf, setTf) {
  const getTplValue = (path) => {
    if (path.startsWith('bullets.')) {
      const [, idx, key] = path.split('.')
      return (tf.bullets && tf.bullets[Number(idx)] && tf.bullets[Number(idx)][key]) || ''
    }
    return tf[path] || ''
  }
  const setTplField = (path, v) => {
    if (path.startsWith('bullets.')) {
      const [, idx, key] = path.split('.')
      const bullets = [...(tf.bullets && tf.bullets.length ? tf.bullets : BLANK_TPL_FIELDS.bullets)]
      bullets[Number(idx)] = { ...bullets[Number(idx)], [key]: v }
      setTf({ ...tf, bullets })
    } else {
      setTf({ ...tf, [path]: v })
    }
  }
  return { getTplValue, setTplField }
}
