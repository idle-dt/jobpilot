/* Tracker modal helpers — loaded once in base.html */

function patchApp(id, field, value) {
    var body = {};
    body[field] = value;
    var token = document.querySelector('meta[name="csrf-token"]');
    fetch('/api/tracker/' + id, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': token ? token.content : ''
        },
        body: JSON.stringify(body)
    }).catch(function(err) {
        console.error('Failed to save field:', field, err);
    });
}

function updateStatus(id, status) {
    var token = document.querySelector('meta[name="csrf-token"]');
    var form = new FormData();
    form.append('status', status);
    fetch('/api/tracker/' + id + '/status', {
        method: 'POST',
        headers: { 'X-CSRFToken': token ? token.content : '' },
        body: form
    }).then(function() {
        var offerCol = document.getElementById('offer-col-' + id);
        if (offerCol) {
            if (status === 'offer' || status === 'accepted') {
                offerCol.classList.remove('tracker-hidden');
            } else {
                offerCol.classList.add('tracker-hidden');
            }
        }
    }).catch(function(err) {
        console.error('Failed to update status:', err);
    });
}
