import { wrap } from 'girder/utilities/PluginUtils';
import { getCurrentUser } from 'girder/auth';

import HierarchyWidget from 'girder/views/widgets/HierarchyWidget';

import WholeTaleHierarchyWidget from '../templates/WholeTaleHierarchyWidget.pug';

wrap(HierarchyWidget, 'render', function (render) {
    var widget = this;
    const folderHeader = widget.$('.g-folder-header-buttons');

    if (getCurrentUser() && widget.parentModel.resourceName === 'folder' && folderHeader.length > 0) {
        render.call(widget);
        $(WholeTaleHierarchyWidget()).prependTo(widget.$('.g-folder-header-buttons'));
        document.getElementsByClassName('g-createTale-button')[0].style.display = 'inline';
    } else {
        render.call(widget);
    }
});

function _analyzeInWT(e) {
    let subdomain = window.location.host.split('.')[0];
    let dashboardUrl = window.location.origin.replace(subdomain, 'dashboard') + '/mine';
    const params = new URLSearchParams();
    params.set('name', 'My Tale');
    params.set('asTale', false);
    const dataSet = [
        {
            'itemId': this.parentModel.id,
            'mountPath': '/',
            '_modelType': 'folder'
        }
    ];
    params.set('dataSet', JSON.stringify(dataSet));
    window.location.assign(dashboardUrl + `?${params.toString()}`);
}

HierarchyWidget.prototype.events['click .g-createTale-button'] = _analyzeInWT;
