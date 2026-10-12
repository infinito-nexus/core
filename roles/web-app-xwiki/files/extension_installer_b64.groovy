// Reads Base64 JSON from placeholder and avoids any quoting issues.
import groovy.json.JsonSlurper
import java.util.Base64

def ext = services.extension
def ns  = "wiki:xwiki"

def b64 = '__WANTED_B64__'
def json = new String(Base64.decoder.decode(b64), 'UTF-8')
def wanted = new JsonSlurper().parseText(json) as List<Map>

if (!wanted || wanted.isEmpty()) {
  println "SKIP: no extensions requested"
  return
}

wanted.each { e ->
  def id  = (e.id ?: "").toString()
  def ver = (e.version ?: "").toString().trim()
  if (!id) { println "ERROR::<missing-id>::Empty extension id in wanted list"; return }

  def already = ext.getInstalledExtension(id, ns)
  if (already && (!ver || already.id?.version?.toString() == ver)) { println "ALREADY_INSTALLED::${id}::${already.id?.version}"; return }

  println "INSTALL_START::${id}::${ver ? ver : 'latest'}"
  def job = null
  def caughtErr = null
  try {
    job = ver ? ext.install(id, ver, ns) : ext.install(id, null, ns)
    job?.join()
  } catch (Throwable t) {
    caughtErr = (t?.message ?: t?.toString())
  }

  def st = job?.status?.state?.name()
  if (st) println "STATE=${st}::${id}"

  def err = job?.status?.error  // singular!
  def errMsg = err ? (err?.message ?: err?.toString()) : null

  def now = ext.getInstalledExtension(id, ns)
  if (now && (!ver || now.id?.version?.toString() == ver)) {
    // Race-safe: Extension Manager can report "Failed to create install plan"
    // while the extension gets installed by the concurrent distribution job.
    if (caughtErr) println "WARN::${id}::${caughtErr}"
    if (errMsg) println "WARN::${id}::${errMsg}"
    println "INSTALLED_OK::${id}::${now.id?.version}"
  } else {
    if (caughtErr) println "ERROR::${id}::${caughtErr}"
    if (errMsg) println "ERROR::${id}::${errMsg}"
    if (!caughtErr && !errMsg && st && st != 'FINISHED') {
      println "ERROR::${id}::Unexpected install state ${st}"
    }
    println now ? "ERROR::${id}::Still on ${now.id?.version}, wanted ${ver}" : "INSTALLED_MISSING::${id}"
  }
}
