import hudson.model.User
import jenkins.security.ApiTokenProperty

def username = System.getenv('JENKINS_MCP_USERNAME')
def tokenName = System.getenv('JENKINS_MCP_TOKEN_NAME')
def tokenFile = System.getenv('JENKINS_MCP_TOKEN_FILE')

if (!username || !tokenName || !tokenFile) {
    return
}

def target = new File(tokenFile)
def user = User.getById(username, true)
def store = user.getProperty(ApiTokenProperty.class).tokenStore

if (target.isFile() && store.findMatchingToken(target.text.trim()) != null) {
    return
}

store.tokenListSortedByName.findAll { it.name == tokenName }.each { store.revokeToken(it.uuid) }
def minted = store.generateNewToken(tokenName)
user.save()

target.parentFile.mkdirs()
target.text = minted.plainValue
target.setReadable(false, false)
target.setWritable(false, false)
target.setReadable(true, true)
target.setWritable(true, true)
