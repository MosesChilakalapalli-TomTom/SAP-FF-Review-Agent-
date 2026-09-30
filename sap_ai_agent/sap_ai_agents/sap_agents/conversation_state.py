class ConversationState:

    def __init__(self):
        self.reset()

    def reset(self):
        self.active_agent = None
        self.waiting_confirmation = False
        self.action = None
        self.payload = None

    def store(self, agent, action, payload):
        self.active_agent = agent
        self.waiting_confirmation = True
        self.action = action
        self.payload = payload

    def confirmed(self):
        return self.waiting_confirmation

    def get_payload(self):
        return self.payload

    def get_action(self):
        return self.action

    def get_agent(self):
        return self.active_agent


conversation_state = ConversationState()